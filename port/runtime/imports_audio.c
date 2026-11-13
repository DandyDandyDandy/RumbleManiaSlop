// nn::audio AudioOut on winmm waveOut. This is the output path of the CRIWARE library statically linked in main
// (CRI Atom mixes in software and streams 16-bit PCM through AudioOut); the engine's FMOD used the audio renderer,
// which is not lifted. Semantics follow xc2-recomp runtime/ov_audio_out.c (MIT, see include/LICENSE.xc2-recomp):
// AppendAudioOutBuffer queues a buffer, a buffer is released once its play time has passed, and
// GetReleasedAudioOutBuffer reports released buffers in append order. The SystemEvent given to OpenDefaultAudioOut
// is signalled on every release.
// Pacing and output are separate. Buffers are released by the wall clock at the exact real-time rate (the game
// appends 5 ms buffers and keeps only three queued; waveOut reports completions in 10 ms steps, which halved the
// game's audio rate when releases were tied to it). The PCM is copied at append time into a stereo ring that a
// feeder thread plays through waveOut in 10 ms blocks, with a short pre-buffer. BR_AUDIO=off skips the device.
//
// Guest layouts: AudioOutBuffer {next, data, capacity, size} at +0, +8, +0x10, +0x18 (only this file reads them);
// AudioOutParameter {int32 sample rate, uint16 channel count, uint16 reserved}, 0 meaning the default. The AudioOut
// object itself is only a key.
#include <windows.h>
#include <mmsystem.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

void rt_os_event_create(uint64_t key, int manual);   // imports_nn.c
void rt_os_event_signal(uint64_t key);

#define OUT_MAX 8
#define QUEUE_MAX 64
#define RATE 48000
#define FMT_PCM16 2
enum { STATE_STARTED = 0, STATE_STOPPED = 1 };

typedef struct { uint64_t buf; volatile LONG done; uint64_t frames; } Queued;
#define RING_FRAMES 16384            // 341 ms of stereo
#define BLOCK_FRAMES 480             // 10 ms device blocks
#define NHDR 6                       // blocks kept queued at the device (60 ms)
#define PREBUF_FRAMES 1440           // start (and restart after an underrun) once 30 ms are buffered
typedef struct Out {
    uint64_t guest, event;
    uint32_t channels, state;
    HWAVEOUT wo;
    int16_t *ring; uint32_t rhead, rcount; int filling;      // stereo frames, under g_lock
    HANDLE feed_thread, feed_event;
    WAVEHDR hdr[NHDR]; int16_t (*blocks)[BLOCK_FRAMES * 2];
    uint64_t underruns, dropped;
    Queued *q[QUEUE_MAX];            // append order; q[0] is the oldest
    int nq;
    // device-less clock
    HANDLE timer_thread;
    volatile LONG closing;
    uint64_t played_frames, queued_frames, start_tick;
} Out;

static Out outs[OUT_MAX];
static CRITICAL_SECTION g_lock;
static INIT_ONCE g_once = INIT_ONCE_STATIC_INIT;
static uint64_t g_appended_bytes, g_released;
static uint64_t g_get_hit, g_get_miss;
static BOOL CALLBACK init_once(PINIT_ONCE o, PVOID p, PVOID *ctx) { (void)o; (void)p; (void)ctx; InitializeCriticalSection(&g_lock); return TRUE; }
static void lock(void) { InitOnceExecuteOnce(&g_once, init_once, NULL, NULL); EnterCriticalSection(&g_lock); }
static void unlock(void) { LeaveCriticalSection(&g_lock); }

static Out *find(uint64_t guest) {
    for (int i = 0; i < OUT_MAX; i++)
        if (outs[i].guest == guest) return &outs[i];
    return NULL;
}
static Out *need(Cpu *c, const char *fn) {
    Out *o = X(0) ? find(X(0)) : NULL;
    if (!o) rt_fatal_c(c, "nn::audio::%s(%#llx): not an open AudioOut", fn, (unsigned long long)X(0));
    return o;
}

// Feeder: keeps NHDR blocks queued at the device, taking frames from the ring (silence while pre-buffering).
static DWORD WINAPI feed_main(void *p) {
    Out *o = p;
    while (!o->closing) {
        for (int i = 0; i < NHDR; i++) {
            WAVEHDR *h = &o->hdr[i];
            if ((h->dwFlags & WHDR_PREPARED) && !(h->dwFlags & WHDR_DONE)) continue;      // still queued
            if (h->dwFlags & WHDR_PREPARED) waveOutUnprepareHeader(o->wo, h, sizeof *h);
            int16_t *dst = o->blocks[i];
            lock();
            if (o->filling && o->rcount >= PREBUF_FRAMES) o->filling = 0;
            uint32_t n = o->filling ? 0 : o->rcount < BLOCK_FRAMES ? o->rcount : BLOCK_FRAMES;
            for (uint32_t k = 0; k < n; k++) {
                uint32_t at = (o->rhead + k) % RING_FRAMES;
                dst[2 * k] = o->ring[2 * at]; dst[2 * k + 1] = o->ring[2 * at + 1];
            }
            o->rhead = (o->rhead + n) % RING_FRAMES; o->rcount -= n;
            if (!o->filling && n < BLOCK_FRAMES) { o->filling = 1; if (o->state == STATE_STARTED) o->underruns++; }
            unlock();
            memset(dst + 2 * n, 0, (BLOCK_FRAMES - n) * 4);
            memset(h, 0, sizeof *h);
            h->lpData = (LPSTR)dst; h->dwBufferLength = BLOCK_FRAMES * 4;
            if (waveOutPrepareHeader(o->wo, h, sizeof *h) == MMSYSERR_NOERROR) waveOutWrite(o->wo, h, sizeof *h);
        }
        WaitForSingleObject(o->feed_event, 20);
    }
    return 0;
}
// Append to the ring as stereo. Under lock.
static void ring_push(Out *o, const int16_t *in, uint64_t frames) {
    for (uint64_t i = 0; i < frames; i++, in += o->channels) {
        int l, r;
        if (o->channels == 6) {   // 5.1 (FL FR FC LFE RL RR): L = FL + 0.707 FC + 0.707 RL, R likewise; LFE dropped
            l = in[0] + (in[2] * 181 >> 8) + (in[4] * 181 >> 8); r = in[1] + (in[2] * 181 >> 8) + (in[5] * 181 >> 8);
            l = l > 32767 ? 32767 : l < -32768 ? -32768 : l; r = r > 32767 ? 32767 : r < -32768 ? -32768 : r;
        } else if (o->channels == 2) { l = in[0]; r = in[1]; }
        else l = r = in[0];
        if (o->rcount == RING_FRAMES) { o->rhead = (o->rhead + 1) % RING_FRAMES; o->rcount--; o->dropped++; }
        uint32_t at = (o->rhead + o->rcount++) % RING_FRAMES;
        o->ring[2 * at] = (int16_t)l; o->ring[2 * at + 1] = (int16_t)r;
    }
}

// Frames played so far by the wall clock. Under lock. The position is advanced incrementally and never passes the
// queued total, so after an underrun the clock resumes from where the data ran out instead of jumping ahead.
static uint64_t timed_frames(Out *o) {
    if (o->state != STATE_STARTED) return o->played_frames;
    uint64_t now = rt_ticks(), adv = (now - o->start_tick) * RATE / 19200000;
    if (adv) {
        o->played_frames += adv;
        o->start_tick += adv * 19200000 / RATE;
        if (o->played_frames >= o->queued_frames) { o->played_frames = o->queued_frames; o->start_tick = now; }
    }
    return o->played_frames;
}
static int g_dbg = -1;
static DWORD WINAPI timer_main(void *p) {
    Out *o = p;
    while (!o->closing) {
        Sleep(1);
        int sig = 0;
        lock();
        // Signal on every tick while a played buffer is waiting to be collected, not only when one finishes: the
        // game can clear the event after a signal it has not acted on yet, and a signal lost that way must not
        // leave it asleep with every buffer played.
        for (int i = 0; i < o->nq && o->guest; i++)
            if (timed_frames(o) >= o->q[i]->frames) o->q[i]->done = 1;
        if (o->guest && o->nq && o->q[0]->done) sig = 1;
        uint64_t ev = o->event;
        if (g_dbg < 0) g_dbg = getenv("BR_AUDIO_DEBUG") != NULL;
        if (g_dbg && o->guest) {      // stall report: no buffer collected for a second
            static uint64_t last_rel, last_change, last_log;
            uint64_t now = rt_ticks();
            if (g_released != last_rel) { last_rel = g_released; last_change = now; }
            else if (now - last_change > 19200000 && now - last_log > 19200000 * 5ull) {
                last_log = now;
                rt_log("audout: stalled: state %u, %d queued (first done %d), played %llu of %llu frames, GetReleased %llu hits %llu misses, event %#llx",
                       o->state, o->nq, o->nq ? (int)o->q[0]->done : -1, (unsigned long long)o->played_frames,
                       (unsigned long long)o->queued_frames, (unsigned long long)g_get_hit, (unsigned long long)g_get_miss, (unsigned long long)ev);
            }
        }
        unlock();
        if (sig && ev) rt_os_event_signal(ev);
    }
    return 0;
}

static uint32_t open_out(Cpu *c, uint64_t guest, uint64_t event, uint64_t param) {
    int32_t rate = param ? (int32_t)LD32(param) : 0;
    uint16_t channels = param ? LD16(param + 4) : 0;
    if (rate && rate != RATE) rt_log("audout: the game asked for %d Hz; the output runs at %d Hz", rate, RATE);
    if (!channels) channels = 2;
    if (channels != 1 && channels != 2 && channels != 6) rt_fatal_c(c, "audout: %u channels", channels);
    if (event) rt_os_event_create(event, 0);
    lock();
    Out *o = find(guest);
    if (!o) o = find(0);
    if (!o) rt_fatal_c(c, "audout: more than %d AudioOuts open", OUT_MAX);
    memset(o, 0, sizeof *o);
    o->guest = guest; o->event = event; o->channels = channels; o->state = STATE_STOPPED;
    const char *e = getenv("BR_AUDIO");
    if (!(e && (!strcmp(e, "off") || !strcmp(e, "0")))) {
        WAVEFORMATEX wf = {WAVE_FORMAT_PCM, 2, RATE, RATE * 4u, 4, 16, 0};
        o->feed_event = CreateEventA(NULL, FALSE, FALSE, NULL);
        if (waveOutOpen(&o->wo, WAVE_MAPPER, &wf, (DWORD_PTR)o->feed_event, 0, CALLBACK_EVENT) != MMSYSERR_NOERROR) o->wo = NULL;
        if (o->wo) {
            o->ring = calloc(RING_FRAMES, 4); o->blocks = calloc(NHDR, sizeof *o->blocks); o->filling = 1;
            o->feed_thread = CreateThread(NULL, 0, feed_main, o, 0, NULL);
        }
    }
    timeBeginPeriod(1);
    o->timer_thread = CreateThread(NULL, 0, timer_main, o, 0, NULL);
    unlock();
    rt_log("audout: opened %#llx, %u channels at %d Hz, %s", (unsigned long long)guest, o->channels, RATE,
           o->wo ? "on the default wave device" : "without a device (timed)");
    return 0;
}
HOSTFN(_ZN2nn5audio27InitializeAudioOutParameterEPNS0_17AudioOutParameterE) { ST32(X(0), 0); ST16(X(0) + 4, 0); ST16(X(0) + 6, 0xcafe); }
HOSTFN(_ZN2nn5audio19OpenDefaultAudioOutEPNS0_8AudioOutERKNS0_17AudioOutParameterE) { RET(open_out(c, X(0), 0, X(1))); }
HOSTFN(_ZN2nn5audio19OpenDefaultAudioOutEPNS0_8AudioOutEPNS_2os11SystemEventERKNS0_17AudioOutParameterE) { RET(open_out(c, X(0), X(1), X(2))); }
HOSTFN(_ZN2nn5audio13ListAudioOutsEPNS0_12AudioOutInfoEi) {   // AudioOutInfo {char name[256]}
    if (X(0) && (int32_t)W(1) > 0) { memset(PTR(0), 0, 256); strcpy(PTR(0), "DeviceOut"); }
    RET((int32_t)W(1) > 0 ? 1 : 0);
}

HOSTFN(_ZN2nn5audio13CloseAudioOutEPNS0_8AudioOutE) {
    lock();
    Out *o = need(c, "CloseAudioOut");
    HWAVEOUT wo = o->wo;
    HANDLE th = o->timer_thread, fth = o->feed_thread;
    o->closing = 1;
    unlock();
    if (th) { WaitForSingleObject(th, INFINITE); CloseHandle(th); }
    if (fth) { SetEvent(o->feed_event); WaitForSingleObject(fth, INFINITE); CloseHandle(fth); }
    if (wo) {
        waveOutReset(wo);            // returns every header before it returns
        for (int i = 0; i < NHDR; i++)
            if (o->hdr[i].dwFlags & WHDR_PREPARED) waveOutUnprepareHeader(wo, &o->hdr[i], sizeof(WAVEHDR));
        waveOutClose(wo);
        CloseHandle(o->feed_event);
    }
    lock();
    rt_log("audout: closed %#llx (%llu underruns, %llu frames dropped)", (unsigned long long)X(0),
           (unsigned long long)o->underruns, (unsigned long long)o->dropped);
    for (int i = 0; i < o->nq; i++) free(o->q[i]);
    free(o->ring); free(o->blocks);
    memset(o, 0, sizeof *o);
    unlock();
}
HOSTFN(_ZN2nn5audio13StartAudioOutEPNS0_8AudioOutE) {
    lock();
    Out *o = need(c, "StartAudioOut");
    if (g_dbg > 0) rt_log("audout: StartAudioOut (state %u)", o->state);
    if (o->state != STATE_STARTED) {
        o->state = STATE_STARTED;
        o->start_tick = rt_ticks();
    }
    unlock();
    RET(0);
}
HOSTFN(_ZN2nn5audio12StopAudioOutEPNS0_8AudioOutE) {
    lock();
    Out *o = need(c, "StopAudioOut");
    if (g_dbg > 0) rt_log("audout: StopAudioOut (state %u)", o->state);
    if (o->state == STATE_STARTED) {
        o->played_frames = timed_frames(o);
        o->state = STATE_STOPPED;
    }
    unlock();
}
HOSTFN(_ZN2nn5audio20AppendAudioOutBufferEPNS0_8AudioOutEPNS0_14AudioOutBufferE) {
    uint64_t buf = X(1);
    if (!buf) rt_fatal_c(c, "nn::audio::AppendAudioOutBuffer: null buffer");
    uint64_t size = LD64(buf + 0x18);
    lock();
    Out *o = need(c, "AppendAudioOutBuffer");
    int ok = o->nq < QUEUE_MAX;
    if (ok) {
        size -= size % (2 * o->channels);
        Queued *q = calloc(1, sizeof *q);
        q->buf = buf;
        o->queued_frames += size / (2 * o->channels);
        q->frames = o->queued_frames;
        o->q[o->nq++] = q;
        g_appended_bytes += size;
        {   // BR_AUDIO_DEBUG: pacing report every 1000 appends
            static int dbg = -1; static uint64_t n, t0, sumq, hit0, miss0; static int minq = 99, maxq;
            if (dbg < 0) dbg = getenv("BR_AUDIO_DEBUG") != NULL;
            if (dbg) {
                if (!n) { t0 = rt_ticks(); hit0 = g_get_hit; miss0 = g_get_miss; }
                sumq += (uint64_t)o->nq; if (o->nq < minq) minq = o->nq; if (o->nq > maxq) maxq = o->nq;
                if (++n == 1000) {
                    rt_log("audout: 1000 appends of %llu bytes in %llu ms; queue depth min %d avg %.1f max %d; GetReleased %llu hits %llu misses",
                           (unsigned long long)size, (unsigned long long)((rt_ticks() - t0) / 19200), minq, (double)sumq / 1000, maxq,
                           (unsigned long long)(g_get_hit - hit0), (unsigned long long)(g_get_miss - miss0));
                    rt_log("audout: ring %u frames, %llu underruns, %llu dropped", o->rcount, (unsigned long long)o->underruns, (unsigned long long)o->dropped);
                    n = 0; sumq = 0; minq = 99; maxq = 0;
                }
            }
        }
        if (o->wo && size) ring_push(o, (const int16_t *)(uintptr_t)LD64(buf + 8), size / (2 * o->channels));
    }
    unlock();
    RET(ok);
}
HOSTFN(_ZN2nn5audio25GetReleasedAudioOutBufferEPNS0_8AudioOutE) {
    uint64_t buf = 0;
    lock();
    Out *o = need(c, "GetReleasedAudioOutBuffer");
    if (o->nq && timed_frames(o) >= o->q[0]->frames) o->q[0]->done = 1;
    if (o->nq && o->q[0]->done) {
        Queued *q = o->q[0];
        buf = q->buf;
        free(q);
        memmove(o->q, o->q + 1, (size_t)--o->nq * sizeof *o->q);
        g_released++;
        g_get_hit++;
    } else g_get_miss++;
    unlock();
    RET(buf);
}
HOSTFN(_ZN2nn5audio16GetAudioOutStateEPKNS0_8AudioOutE) { lock(); uint32_t s = need(c, "GetAudioOutState")->state; unlock(); RET(s); }
HOSTFN(_ZN2nn5audio23GetAudioOutChannelCountEPKNS0_8AudioOutE) { lock(); uint32_t n = need(c, "GetAudioOutChannelCount")->channels; unlock(); RET(n); }
HOSTFN(_ZN2nn5audio21GetAudioOutSampleRateEPKNS0_8AudioOutE) { RET(RATE); }
HOSTFN(_ZN2nn5audio23GetAudioOutSampleFormatEPKNS0_8AudioOutE) { RET(FMT_PCM16); }
HOSTFN(_ZN2nn5audio21SetAudioOutBufferInfoEPNS0_14AudioOutBufferEPvmm) { ST64(X(0), 0); ST64(X(0) + 8, X(1)); ST64(X(0) + 0x10, X(2)); ST64(X(0) + 0x18, X(3)); }
HOSTFN(_ZN2nn5audio28GetAudioOutBufferDataPointerEPKNS0_14AudioOutBufferE) { RET(LD64(X(0) + 8)); }
HOSTFN(_ZN2nn5audio25GetAudioOutBufferDataSizeEPKNS0_14AudioOutBufferE) { RET(LD64(X(0) + 0x18)); }

// The output device as the game sees it: one stereo TV output that never changes.
HOSTFN(_ZN2nn5audio24GetActiveAudioDeviceNameEPNS0_15AudioDeviceNameE) {
    if (X(0)) { memset(PTR(0), 0, 256); strcpy(PTR(0), "AudioTvOutput"); }
    RET(0);
}
HOSTFN(_ZN2nn5audio41GetActiveAudioDeviceChannelCountForOutputEv) { RET(2); }
HOSTFN(_ZN2nn5audio39AcquireAudioDeviceNotificationForOutputEPNS_2os11SystemEventE) { rt_os_event_create(X(0), 0); RET(0); }

void rt_audio_stats(uint64_t *appended_bytes, uint64_t *released) { *appended_bytes = g_appended_bytes; *released = g_released; }
