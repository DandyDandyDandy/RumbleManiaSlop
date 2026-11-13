// Diagnostic Vulkan layer for the port: logs the present mode the engine asks for in vkCreateSwapchainKHR and can
// override it. Not part of the game; enable it for one run only with
//   VK_LAYER_PATH=<this dir>  VK_INSTANCE_LAYERS=VK_LAYER_BR_swapchain  [BR_VK_PRESENT_MODE=0..3]  BR_VK_LOG=<file>
// Present modes: 0 IMMEDIATE, 1 MAILBOX, 2 FIFO, 3 FIFO_RELAXED. One instance and one device are assumed.
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#include <vulkan/vk_layer.h>

static PFN_vkGetInstanceProcAddr next_gipa;
static PFN_vkGetDeviceProcAddr next_gdpa;
static PFN_vkCreateSwapchainKHR next_create_swapchain;
static PFN_vkDestroyInstance next_destroy_instance;
static PFN_vkDestroyDevice next_destroy_device;

static void logf_(const char *fmt, ...) {
    const char *path = getenv("BR_VK_LOG");
    if (!path) return;
    FILE *f = fopen(path, "a");
    if (!f) return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

static VKAPI_ATTR VkResult VKAPI_CALL br_CreateInstance(const VkInstanceCreateInfo *ci, const VkAllocationCallbacks *a, VkInstance *out) {
    VkLayerInstanceCreateInfo *li = (VkLayerInstanceCreateInfo *)ci->pNext;
    while (li && !(li->sType == VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO && li->function == VK_LAYER_LINK_INFO))
        li = (VkLayerInstanceCreateInfo *)li->pNext;
    if (!li) return VK_ERROR_INITIALIZATION_FAILED;
    next_gipa = li->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    li->u.pLayerInfo = li->u.pLayerInfo->pNext;
    PFN_vkCreateInstance create = (PFN_vkCreateInstance)next_gipa(VK_NULL_HANDLE, "vkCreateInstance");
    VkResult r = create(ci, a, out);
    if (r == VK_SUCCESS) next_destroy_instance = (PFN_vkDestroyInstance)next_gipa(*out, "vkDestroyInstance");
    logf_("layer: instance created (%d)", (int)r);
    return r;
}
static VKAPI_ATTR VkResult VKAPI_CALL br_CreateDevice(VkPhysicalDevice pd, const VkDeviceCreateInfo *ci, const VkAllocationCallbacks *a, VkDevice *out) {
    VkLayerDeviceCreateInfo *li = (VkLayerDeviceCreateInfo *)ci->pNext;
    while (li && !(li->sType == VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO && li->function == VK_LAYER_LINK_INFO))
        li = (VkLayerDeviceCreateInfo *)li->pNext;
    if (!li) return VK_ERROR_INITIALIZATION_FAILED;
    PFN_vkGetInstanceProcAddr gipa = li->u.pLayerInfo->pfnNextGetInstanceProcAddr;
    next_gdpa = li->u.pLayerInfo->pfnNextGetDeviceProcAddr;
    li->u.pLayerInfo = li->u.pLayerInfo->pNext;
    PFN_vkCreateDevice create = (PFN_vkCreateDevice)gipa(VK_NULL_HANDLE, "vkCreateDevice");
    VkResult r = create(pd, ci, a, out);
    if (r == VK_SUCCESS) {
        next_create_swapchain = (PFN_vkCreateSwapchainKHR)next_gdpa(*out, "vkCreateSwapchainKHR");
        next_destroy_device = (PFN_vkDestroyDevice)next_gdpa(*out, "vkDestroyDevice");
    }
    logf_("layer: device created (%d)", (int)r);
    return r;
}
static VKAPI_ATTR VkResult VKAPI_CALL br_CreateSwapchainKHR(VkDevice d, const VkSwapchainCreateInfoKHR *ci, const VkAllocationCallbacks *a, VkSwapchainKHR *out) {
    VkSwapchainCreateInfoKHR c = *ci;
    const char *force = getenv("BR_VK_PRESENT_MODE");
    if (force && *force) c.presentMode = (VkPresentModeKHR)atoi(force);
    VkResult r = next_create_swapchain(d, &c, a, out);
    logf_("layer: vkCreateSwapchainKHR %ux%u, %u images, engine asked for present mode %d, created with %d -> result %d",
          ci->imageExtent.width, ci->imageExtent.height, ci->minImageCount, (int)ci->presentMode, (int)c.presentMode, (int)r);
    return r;
}

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL br_GetDeviceProcAddr(VkDevice d, const char *name) {
    if (!strcmp(name, "vkGetDeviceProcAddr")) return (PFN_vkVoidFunction)br_GetDeviceProcAddr;
    if (!strcmp(name, "vkCreateSwapchainKHR")) return (PFN_vkVoidFunction)br_CreateSwapchainKHR;
    return next_gdpa(d, name);
}
static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL br_GetInstanceProcAddr(VkInstance i, const char *name) {
    if (!strcmp(name, "vkGetInstanceProcAddr")) return (PFN_vkVoidFunction)br_GetInstanceProcAddr;
    if (!strcmp(name, "vkCreateInstance")) return (PFN_vkVoidFunction)br_CreateInstance;
    if (!strcmp(name, "vkCreateDevice")) return (PFN_vkVoidFunction)br_CreateDevice;
    if (!strcmp(name, "vkGetDeviceProcAddr")) return (PFN_vkVoidFunction)br_GetDeviceProcAddr;
    if (!strcmp(name, "vkCreateSwapchainKHR")) return (PFN_vkVoidFunction)br_CreateSwapchainKHR;
    return next_gipa ? next_gipa(i, name) : NULL;
}

__declspec(dllexport) VKAPI_ATTR VkResult VKAPI_CALL vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface *v) {
    if (v->loaderLayerInterfaceVersion > 2) v->loaderLayerInterfaceVersion = 2;
    v->pfnGetInstanceProcAddr = br_GetInstanceProcAddr;
    v->pfnGetDeviceProcAddr = br_GetDeviceProcAddr;
    v->pfnGetPhysicalDeviceProcAddr = NULL;
    return VK_SUCCESS;
}
