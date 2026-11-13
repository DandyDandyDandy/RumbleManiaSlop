// Stand-alone test of the online transport (netplay.c): a host and two guests in one process over the loopback
// interface, with simulated packet loss. Build and run: python port\runtime\build_runtime.py --test-net
#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../netplay.h"

static int g_fail, g_quiet;
void np_logf(const char *fmt, ...) {
    va_list ap;
    if (g_quiet) return;
    va_start(ap, fmt);
    printf("   ");
    vprintf(fmt, ap);
    printf("\n");
    va_end(ap);
}
#define CHECK(cond, what) do { if (cond) printf("ok    %s\n", what); else { printf("FAIL  %s\n", what); g_fail++; } } while (0)

typedef struct Got { int joined, failed, fail_reason, closed, close_reason, peers_ev, flags_ev; int nrel, nunrel, order_ok, big_ok, target_hits, greets; uint32_t next[3]; uint64_t bytes; } Got;
static Np *np[3];
static Got got[3];
static uint64_t ids[3];

static int who(uint64_t id) { for (int i = 0; i < 3; i++) if (ids[i] == id) return i; return -1; }
static void pump(int ms) {
    for (ULONGLONG end = GetTickCount64() + (ULONGLONG)ms; GetTickCount64() < end;) {
        for (int i = 0; i < 3; i++) {
            NpEvent e;
            while (np[i] && np_poll(np[i], &e)) {
                Got *g = &got[i];
                switch (e.type) {
                case NP_EV_JOINED: g->joined++; break;
                case NP_EV_FAILED: g->failed++; g->fail_reason = e.reason; break;
                case NP_EV_CLOSED: g->closed++; g->close_reason = e.reason; break;
                case NP_EV_PEERS: g->peers_ev++; if (i == 0) { uint64_t pl2[NP_MAX_PEERS]; int n2 = np_peers(np[0], pl2, NP_MAX_PEERS); for (int q = 1; q < n2; q++) np_send(np[0], (const uint8_t *)"G", 1, 1, NP_TO_TARGETS, &pl2[q], 1); } break;
                case NP_EV_FLAGS: g->flags_ev++; break;
                case NP_EV_DATA: {
                    int from = who(e.peer);
                    g->bytes += e.len;
                    if (e.len >= 5 && e.data[0] == 'R' && from >= 0) {          // ordered reliable counter
                        uint32_t v;
                        memcpy(&v, e.data + 1, 4);
                        if (v != g->next[from]) g->order_ok = 0;
                        g->next[from] = v + 1;
                        g->nrel++;
                        if (!e.reliable) g->order_ok = 0;
                    } else if (e.len >= 1 && e.data[0] == 'U') g->nunrel++;
                    else if (e.len == 100000 && e.data[0] == 'B') {
                        int ok = 1;
                        for (uint32_t k = 1; k < e.len; k++) ok &= e.data[k] == (uint8_t)(k * 7);
                        g->big_ok += ok;
                    } else if (e.len >= 1 && e.data[0] == 'T') g->target_hits++;
                    else if (e.len == 1 && e.data[0] == 'G') { g->greets++; if (!g->joined) g->order_ok = 0; }
                    np_free(e.data);
                    break;
                }
                }
            }
        }
        Sleep(1);
    }
}
static int wait_for(int *flag, int ms) {
    for (int t = 0; t < ms && !*flag; t += 20) pump(20);
    return *flag;
}

int main(void) {
    NpConfig cfg = {0};
    char code[64], bad[64];
    uint32_t ip, secret;
    int port;
    setvbuf(stdout, NULL, _IONBF, 0);

    np_code_format(0xc0a80117, 7, 0xadbeef, code, sizeof code);
    CHECK(np_code_parse(code, &ip, &port, &secret) && ip == 0xc0a80117 && port == 7 && secret == 0xadbeef && strlen(code) == 14, "room code round trip");
    CHECK(!np_code_parse("ABCD-EFGH", &ip, &port, &secret) && !np_code_parse("!!!!-!!!!-!!!!", &ip, &port, &secret), "malformed codes are refused");

    cfg.port = 24811;
    cfg.upnp = 0;
    snprintf(cfg.public_ip, sizeof cfg.public_ip, "127.0.0.1");
    cfg.loss_percent = 20;
    for (int i = 0; i < 3; i++) { np[i] = np_create(); got[i].order_ok = 1; }

    np_host(np[0], 2, &cfg);
    CHECK(wait_for(&got[0].joined, 3000) && np_state(np[0]) == NP_INROOM, "host creates a room");
    np_code(np[0], code, sizeof code);
    printf("   code %s\n", code);
    ids[0] = np_local_id(np[0]);

    // a guest with the right address but a wrong secret gets nothing
    CHECK(np_code_parse(code, &ip, &port, &secret), "host code parses");
    np_code_format(ip, port, secret ^ 1, bad, sizeof bad);
    np_join(np[1], bad, 2, &cfg);
    pump(1500);
    CHECK(np_state(np[1]) == NP_CONNECTING && !got[1].joined, "wrong secret: no answer from the host");
    np_leave(np[1]);
    pump(100);
    memset(&got[1], 0, sizeof got[1]);
    got[1].order_ok = 1;

    // wrong purpose is refused with a reason
    np_join(np[1], code, 1, &cfg);
    CHECK(wait_for(&got[1].failed, 6000) && got[1].fail_reason == NP_FAIL_VERSION, "wrong room purpose is refused");
    memset(&got[1], 0, sizeof got[1]);
    got[1].order_ok = 1;

    np_join(np[1], code, 2, &cfg);
    np_join(np[2], code, 2, &cfg);
    CHECK(wait_for(&got[1].joined, 8000) && wait_for(&got[2].joined, 8000), "two guests join through 20% packet loss");
    ids[1] = np_local_id(np[1]);
    ids[2] = np_local_id(np[2]);
    pump(500);
    uint64_t pl[3][NP_MAX_PEERS];
    int same = 1;
    for (int i = 0; i < 3; i++) same &= np_peers(np[i], pl[i], NP_MAX_PEERS) == 3;
    for (int i = 1; i < 3 && same; i++) same &= !memcmp(pl[0], pl[i], 24);
    CHECK(same && pl[0][0] == ids[0] && np_master_id(np[1]) == ids[0] && np_master_id(np[2]) == ids[0], "all three agree on the peer list, host first and master");
    CHECK(ids[0] && ids[1] && ids[2] && ids[0] != ids[1] && ids[1] != ids[2], "peer ids are distinct");
    CHECK(got[1].greets >= 1 && got[2].greets >= 1 && got[1].order_ok && got[2].order_ok, "what the host sends a guest the moment it appears arrives, after the join event");

    // reliable ordered traffic from everybody to everybody, with unreliable datagrams in between
    for (uint32_t k = 0; k < 400; k++) {
        for (int i = 0; i < 3; i++) {
            uint8_t m[64] = {'R'};
            memcpy(m + 1, &k, 4);
            np_send(np[i], m, 5 + (k % 50), 1, NP_TO_OTHERS, NULL, 0);
            m[0] = 'U';
            np_send(np[i], m, 20, 0, NP_TO_OTHERS, NULL, 0);
        }
        if (k % 20 == 0) pump(10);
    }
    uint8_t *big = malloc(100000);
    big[0] = 'B';
    for (uint32_t k = 1; k < 100000; k++) big[k] = (uint8_t)(k * 7);
    np_send(np[1], big, 100000, 1, NP_TO_OTHERS, NULL, 0);          // guest -> host -> other guest, fragmented
    np_send(np[2], (const uint8_t *)"T", 1, 1, NP_TO_TARGETS, &ids[1], 1);   // guest -> one guest only
    np_send(np[0], (const uint8_t *)"T", 1, 1, NP_TO_TARGETS, &ids[2], 1);
    for (int t = 0; t < 400 && !(got[0].nrel == 800 && got[1].nrel == 800 && got[2].nrel == 800 && got[0].big_ok && got[2].big_ok); t++) pump(50);
    CHECK(got[0].nrel == 800 && got[1].nrel == 800 && got[2].nrel == 800, "every reliable message arrives exactly once");
    CHECK(got[0].order_ok && got[1].order_ok && got[2].order_ok, "reliable messages arrive in order per sender");
    CHECK(got[0].big_ok == 1 && got[2].big_ok == 1 && got[1].big_ok == 0, "a 100 kB message is relayed intact and not echoed");
    printf("   unreliable received: %d %d %d of 800 each\n", got[0].nunrel, got[1].nunrel, got[2].nunrel);
    CHECK(got[0].nunrel > 300 && got[0].nunrel <= 800 && got[1].nunrel > 200 && got[2].nunrel > 200, "unreliable datagrams mostly arrive, none duplicated");
    pump(300);
    CHECK(got[1].target_hits == 1 && got[2].target_hits == 1 && got[0].target_hits == 0, "targeted messages reach only their target");

    int64_t t0 = np_time_ms(np[0]), t1 = np_time_ms(np[1]), t2 = np_time_ms(np[2]);
    printf("   room clock difference to the host: %lld ms, %lld ms; ping %d / %d ms\n", (long long)(t1 - t0), (long long)(t2 - t0), np_rtt(np[1], ids[0]), np_rtt(np[2], ids[0]));
    CHECK(llabs(t1 - t0) < 30 && llabs(t2 - t0) < 30, "guests' room clocks follow the host's");

    CHECK(!np_set_can_participate(np[1], 0) && np_set_can_participate(np[0], 0), "only the host may close the room");
    for (int t = 0; t < 60 && !(got[1].flags_ev && got[2].flags_ev); t++) pump(50);
    CHECK(!np_can_participate(np[1]) && !np_can_participate(np[2]) && got[1].flags_ev == 1, "closing the room reaches the guests");
    Np *late = np_create();
    Np *keep = np[2];
    np[2] = late;
    Got saved = got[2];
    memset(&got[2], 0, sizeof got[2]);
    np_join(late, code, 2, &cfg);
    CHECK(wait_for(&got[2].failed, 6000) && got[2].fail_reason == NP_FAIL_CLOSED_ROOM, "a closed room refuses new guests");
    np_destroy(late);
    np[2] = keep;
    got[2] = saved;

    // a guest leaves: the others see the list shrink; then the host leaves: the remaining guest is told
    int before0 = got[0].peers_ev, before1 = got[1].peers_ev;
    np_leave(np[2]);
    for (int t = 0; t < 100 && !(got[0].peers_ev > before0 && got[1].peers_ev > before1); t++) pump(50);
    CHECK(np_peers(np[0], pl[0], NP_MAX_PEERS) == 2 && np_peers(np[1], pl[1], NP_MAX_PEERS) == 2 && np_state(np[2]) == NP_IDLE, "a guest leaving shrinks the peer list");
    np_leave(np[0]);
    CHECK(wait_for(&got[1].closed, 12000) && got[1].close_reason == NP_CLOSE_HOST_LEFT && np_state(np[1]) == NP_IDLE, "the host leaving closes the room for the guest");

    // garbage at a host's port does not disturb it
    g_quiet = 1;
    np_host(np[0], 2, &cfg);
    got[0].joined = 0;
    wait_for(&got[0].joined, 3000);
    np_code(np[0], code, sizeof code);
    {
        WSADATA w;
        WSAStartup(MAKEWORD(2, 2), &w);
        SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        struct sockaddr_in a = {0};
        uint8_t junk[1500];
        a.sin_family = AF_INET; a.sin_port = htons(24811); a.sin_addr.s_addr = htonl(0x7f000001);
        srand(1);
        for (int k = 0; k < 20000; k++) {
            int n = rand() % 1400;
            for (int j = 0; j < n; j++) junk[j] = (uint8_t)rand();
            if (k % 2) memcpy(junk, "BRN1", 4);
            if (k % 4 == 1) junk[4] = (uint8_t)(1 + rand() % 21);
            sendto(s, (const char *)junk, n, 0, (struct sockaddr *)&a, sizeof a);
            if (k % 500 == 0) pump(4);
        }
        closesocket(s);
    }
    memset(&got[1], 0, sizeof got[1]);
    np_join(np[1], code, 2, &cfg);
    CHECK(wait_for(&got[1].joined, 8000), "host still accepts a guest after 20000 garbage packets");
    for (int i = 0; i < 3; i++) np_destroy(np[i]);
    printf(g_fail ? "\n%d FAILED\n" : "\nall passed\n", g_fail);
    return g_fail != 0;
}
