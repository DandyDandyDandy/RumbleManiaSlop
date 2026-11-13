// UPnP port mapping for a hosted room, through the NAT helper that ships with Windows (the "UPnPNAT" COM object,
// which speaks to the router on the local network). Late-bound through IDispatch, so no SDK header is needed.
// Called on the session thread only: the calls can take seconds.
#define COBJMACROS
#include <windows.h>
#include <oleauto.h>
#include <stdio.h>
#include "netplay.h"

static const CLSID CLSID_UPnPNAT_ = {0xAE1E00AA, 0x3FD5, 0x403C, {0x8A, 0x27, 0x2B, 0xBD, 0xC3, 0x0C, 0xD0, 0xE1}};

// args are in call order; out may be NULL
static HRESULT invoke(IDispatch *d, const wchar_t *name, WORD kind, VARIANT *args, int n, VARIANT *out) {
    DISPID id;
    LPOLESTR nm = (LPOLESTR)name;
    HRESULT hr = IDispatch_GetIDsOfNames(d, &IID_NULL, &nm, 1, LOCALE_USER_DEFAULT, &id);
    if (FAILED(hr)) return hr;
    VARIANT rev[8];
    for (int i = 0; i < n; i++) rev[i] = args[n - 1 - i];
    DISPPARAMS dp = {rev, NULL, (UINT)n, 0};
    VARIANT tmp;
    VariantInit(&tmp);
    hr = IDispatch_Invoke(d, id, &IID_NULL, LOCALE_USER_DEFAULT, kind, &dp, out ? out : &tmp, NULL, NULL);
    if (!out) VariantClear(&tmp);
    return hr;
}
static IDispatch *collection(void) {
    IDispatch *nat = NULL, *col = NULL;
    VARIANT v;
    VariantInit(&v);
    if (FAILED(CoCreateInstance(&CLSID_UPnPNAT_, NULL, CLSCTX_ALL, &IID_IDispatch, (void **)&nat)) || !nat) return NULL;
    // Windows looks for the router in the background: the collection can be missing on the first asks. Without a
    // UPnP router it stays missing (measured: still none after 8 s), so the wait is kept short.
    for (int k = 0; k < 6 && !col; k++) {
        if (k) Sleep(500);
        if (SUCCEEDED(invoke(nat, L"StaticPortMappingCollection", DISPATCH_PROPERTYGET, NULL, 0, &v)) && v.vt == VT_DISPATCH && v.pdispVal) {
            col = v.pdispVal;                                        // keep the reference
            v.vt = VT_EMPTY;
        }
        VariantClear(&v);
    }
    IDispatch_Release(nat);
    return col;
}
static void bstr_arg(VARIANT *v, const wchar_t *s) { v->vt = VT_BSTR; v->bstrVal = SysAllocString(s); }
static void long_arg(VARIANT *v, long x) { v->vt = VT_I4; v->lVal = x; }

int upnp_map(uint16_t port, const char *local_ip, char *ext_ip, size_t n) {
    int ok = 0;
    if (n) ext_ip[0] = 0;
    HRESULT ci = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    IDispatch *col = collection();
    if (col) {
        VARIANT a[6], r;
        wchar_t wip[64];
        for (int i = 0; i < 6; i++) VariantInit(&a[i]);
        VariantInit(&r);
        MultiByteToWideChar(CP_ACP, 0, local_ip, -1, wip, 64);
        long_arg(&a[0], port);
        bstr_arg(&a[1], L"UDP");
        long_arg(&a[2], port);
        bstr_arg(&a[3], wip);
        a[4].vt = VT_BOOL; a[4].boolVal = VARIANT_TRUE;
        bstr_arg(&a[5], L"Banana Rumble PC room");
        if (SUCCEEDED(invoke(col, L"Add", DISPATCH_METHOD, a, 6, &r)) && r.vt == VT_DISPATCH && r.pdispVal) {
            VARIANT e;
            VariantInit(&e);
            ok = 1;
            if (SUCCEEDED(invoke(r.pdispVal, L"ExternalIPAddress", DISPATCH_PROPERTYGET, NULL, 0, &e)) && e.vt == VT_BSTR && e.bstrVal)
                WideCharToMultiByte(CP_ACP, 0, e.bstrVal, -1, ext_ip, (int)n, NULL, NULL);
            VariantClear(&e);
        }
        VariantClear(&r);
        for (int i = 0; i < 6; i++) VariantClear(&a[i]);
        IDispatch_Release(col);
    }
    if (SUCCEEDED(ci)) CoUninitialize();
    return ok;
}

void upnp_unmap(uint16_t port) {
    HRESULT ci = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    IDispatch *col = collection();
    if (col) {
        VARIANT a[2];
        VariantInit(&a[0]);
        VariantInit(&a[1]);
        long_arg(&a[0], port);
        bstr_arg(&a[1], L"UDP");
        invoke(col, L"Remove", DISPATCH_METHOD, a, 2, NULL);
        VariantClear(&a[1]);
        IDispatch_Release(col);
    }
    if (SUCCEEDED(ci)) CoUninitialize();
}
