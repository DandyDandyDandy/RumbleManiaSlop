// Helpers shared by the generated (api_gen.c) and hand-written (api_hand.c, icall.c) il2cpp_* exports.
#pragma once
#include "rt.h"
#define EXPORT __declspec(dllexport)

Cpu *api_enter(const char *name);                     // first call initialises the runtime; returns the thread's Cpu
void api_call(Cpu *c, uint64_t offset, const char *name);   // call main+offset with the registers set up
void api_stub(const char *name, int *logged);
uint64_t api_guest(const char *name);                 // guest address of an API function / vm target (fatal if unknown)
