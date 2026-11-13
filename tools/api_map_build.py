"""Build work/unity/api/il2cpp_api_map.tsv and runtime_symbols.tsv.

Inputs: api_map_data.py (the 135 wrappers found in main), the DO_API prototypes of the exact-version
il2cpp-api-functions.h, and up_users.tsv (which player functions use each pointer in the Windows UnityPlayer.dll).
"""
from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_map_data import W

OUT = W + r'\work\unity\api'
HDR = UNITY_EDITOR + r'\il2cpp\libil2cpp\il2cpp-api-functions.h'
H, M, L = 'high', 'medium', 'low'

# confidence upgrades established after the first pass
W['il2cpp_gc_enable'] = (0x465700, H, 'b 0x4271dc -> b 0x3e2210 (bdwgc GC_enable: GC_dont_gc-- on global 0x6c9f558); API src order enable,disable and BoehmGC.cpp order Disable(0x4271d8),Enable(0x4271dc) agree')
W['il2cpp_gc_disable'] = (0x465710, H, 'b 0x4271d8 -> b 0x3e2270 (bdwgc GC_disable: GC_dont_gc++ on global 0x6c9f558); see il2cpp_gc_enable')
W['il2cpp_string_intern'] = (0x465a30, H, 'b 0x456b90 (String::Intern, lazily builds intern table); the mscorlib icall String::InternalIntern 0x46b44c (target of managed System.String::Intern/InternalIntern) tail-calls this wrapper')
W['il2cpp_set_find_plugin_callback'] = (0x465c70, H, 'b 0x407308 (PlatformInvoke::SetFindPluginCallback, right after Object.cpp fns) -> b 0x447048 (stores fn ptr to global 0x6ca17d8 = os::LibraryLoader::SetFindPluginCallback); single engine caller passes a function address, as Windows MonoManager ctor')

# name -> (vm_addr or None, vm_name, confidence of that identification, how to re-create / evidence)
A = {}


def a(name, addr, vm, conf, note):
    A[name] = (addr, vm, conf, note)


a('il2cpp_init_utf16', None, '', H, 'no wrapper; re-create: convert UTF-16 to UTF-8, call il2cpp_init 0x4652c0 (utils::StringUtils::Utf16ToUtf8 not located)')
a('il2cpp_shutdown', 0x46dfc0, 'il2cpp::vm::Runtime::Shutdown', H, 'takes the same init lock (0x6ca24a0) as Runtime::Init, fires "ProcessExit" (FireProcessExitEvent inlined); sits between Init and IsShuttingDown/SetConfigDir as in Runtime.cpp; called by the Environment::Exit icall 0x46b320')
a('il2cpp_set_temp_dir', None, '', H, 'vm::Path::SetTempPath not in main: only two std::string-assign setters exist in the runtime range (0x46e264 config dir, 0x403e04 data dir); stub')
a('il2cpp_set_commandline_arguments_utf16', None, '', M, 'UTF-16 overload of Environment::SetMainArgs not located; re-create by converting and calling 0x459af0')
a('il2cpp_set_config_utf16', None, '', H, 'Runtime::SetConfigUtf16 not emitted (nothing between SetConfigDir 0x46e264 and SetConfig 0x46e278); re-create by converting and calling 0x46e278')
a('il2cpp_resolve_icall', 0x41eadc, 'il2cpp::vm::InternalCalls::Resolve', H, 'given anchor; only caller is il2cpp_codegen_resolve_icall 0x44c070; wrapper = tail call')
a('il2cpp_alloc', 0x419620, 'il2cpp::utils::Memory::Malloc', H, 'br callbacks.malloc_func (global 0x6442718+0); the fn il2cpp_type_get_name calls for its buffer; wrapper = tail call')
a('il2cpp_array_get_byte_length', 0x406370, 'il2cpp::vm::Array::GetByteLength', M, 'in Array.cpp range; multiplies bounds lengths over klass->rank by klass->element_size (0x104); wrapper = tail call')
a('il2cpp_class_is_inited', None, '', H, 'inline in source: klass->initialized = bit1 of the u16 bitfield at Il2CppClass+0x135')
a('il2cpp_class_is_assignable_from', 0x3ee600, 'il2cpp::vm::Class::IsAssignableFrom(Il2CppClass*,Il2CppClass*)', H, 'target of il2cpp_codegen_class_is_assignable_from 0x44c900 (4.5k generated call sites) and of the reflection overload 0x3ee894 (icall type_is_assignable_from)')
a('il2cpp_class_get_element_class', 0x3ed094, 'il2cpp::vm::Class::GetElementClass', M, 'ldr x0,[x0,#0x40] (element_class), immediately before GetEnumBaseType 0x3ed09c as in Class.cpp')
a('il2cpp_class_get_events', 0x3ed0b0, 'il2cpp::vm::Class::GetEvents', M, 'iterator with 0x38 stride (sizeof EventInfo) next to SetupEvents 0x3ed140 (klass->events 0x88); Class.cpp order')
a('il2cpp_class_get_interfaces', 0x3ed5c0, 'il2cpp::vm::Class::GetInterfaces', M, 'iterator over implementedInterfaces (0xa8), between GetInstanceSize and GetMethods as in Class.cpp')
a('il2cpp_class_get_properties', 0x3ee098, 'il2cpp::vm::Class::GetProperties', M, 'iterator with 0x28 stride (sizeof PropertyInfo) next to SetupProperties 0x3ee120 (klass->properties 0x90)')
a('il2cpp_class_get_property_from_name', None, '', M, 'Class::GetPropertyFromName not found between GetProperties 0x3ee098 and GetValueSize 0x3ee29c; re-create over GetProperties')
a('il2cpp_class_get_method_from_name', 0x3ed9bc, 'il2cpp::vm::Class::GetMethodFromName', H, 'mov w3,#0; b GetMethodFromNameFlags 0x3ed9d0; runtime calls it with (".ctor",0) and ("Invoke",-1)')
a('il2cpp_type_get_name_chunked', None, '', L, 'Type::GetNameChunkedRecurse not located; stub (unused by the Windows player)')
a('il2cpp_class_num_fields', 0x3ee088, 'il2cpp::vm::Class::GetNumFields', M, 'ldrh w0,[x0,#0x124] (field_count), immediately before GetParent 0x3ee090 as in Class.cpp')
a('il2cpp_class_value_size', 0x3ee29c, 'il2cpp::vm::Class::GetValueSize', H, '(klass, uint32_t* align): returns instance_size-0x10, stores minimumAlignment(0x133) to *align, "Could not load type" path')
a('il2cpp_class_get_type_token', None, '', H, 'inline in source: ldr w0,[klass,#0x11c] (token; same offset il2cpp_custom_attrs_from_class reads)')
a('il2cpp_class_has_references', 0x3f11a0, 'il2cpp::vm::Class::HasReferences', M, 'ensures size_inited (bit8) under the class lock then returns bit5 (has_references) of the bitfield @0x135')
a('il2cpp_class_get_data_size', None, '', M, 'inline in source: ldr w0,[klass,#0x10c] (static_fields_size; offset from headers, neighbours 0x104/0x114/0x118 verified in main)')
a('il2cpp_class_get_static_field_data', None, '', H, 'inline in source: ldr x0,[klass,#0xb8] (static_fields; offset verified in Field code in main)')
a('il2cpp_class_get_bitmap_size', None, '', L, 'Class::GetBitmapSize not located ("testing only" in source); stub')
a('il2cpp_class_get_bitmap', None, '', L, 'Class::GetBitmap not located ("testing only" in source); stub')
a('il2cpp_stats_dump_to_file', None, '', M, 'no counterpart located; stub returning false')
a('il2cpp_stats_get_value', None, '', M, 'no counterpart located (il2cpp_runtime_stats global not identified); stub returning 0')
a('il2cpp_domain_get_assemblies', 0x4066ec, 'il2cpp::vm::Assembly::GetAllAssemblies', M, 'returns &s_Assemblies (std::vector at 0x6ca0060, the vector Assembly::Load 0x406900 iterates); wrapper: *size = end-begin, return begin')
a('il2cpp_format_exception', None, '', L, 'utils::Exception::FormatException not located; stub')
a('il2cpp_format_stack_trace', None, '', L, 'utils::Exception::FormatStackTrace not located; stub')
a('il2cpp_unhandled_exception', 0x46ec50, 'il2cpp::vm::Runtime::UnhandledException', H, 'Domain::GetCurrent/GetRoot, GetFieldFromName(appdomain,"UnhandledException"), invokes delegate "Invoke"; 5 runtime callers')
a('il2cpp_field_get_value_object', 0x46c2b0, 'il2cpp::vm::Field::GetValueObject', H, '(field,obj); target of the RuntimeFieldInfo::GetValueInternal icall 0x4266c0 (loads reflField->field then tail-calls)')
a('il2cpp_field_set_value', 0x46c950, 'il2cpp::vm::Field::SetValue', H, '(obj,field,value): SetValueRaw(field->type, obj+field->offset, value, false) 0x46bfe0; mirror image of Field::GetValue 0x46bfc4')
a('il2cpp_field_static_get_value', 0x46c968, 'il2cpp::vm::Field::StaticGetValue', M, 'mov x2,#0; b StaticGetValueInternal 0x46c970 (field,value,thread=NULL)')
a('il2cpp_field_static_set_value', None, '', M, 'Field::StaticSetValue not found in the Field.cpp range (0x46bfa0-0x46cb24); the SetValueInternal icall 0x4266f8 open-codes static stores; re-create with ClassInit 0x46c400 + SetValueRaw 0x46bfe0')
a('il2cpp_field_set_value_object', None, '', M, 'Field::SetInstanceFieldValueObject not found in the Field.cpp range; re-create (store + write barrier 0x429170)')
a('il2cpp_field_is_literal', None, '', H, 'inline in source: (field->type->attrs & FIELD_ATTRIBUTE_LITERAL 0x40) != 0')
a('il2cpp_gc_is_disabled', None, '', M, 'GarbageCollector::IsDisabled not emitted (nothing between Enable 0x4271dc and SetMode 0x4271e0); re-create: read bdwgc GC_dont_gc counter at 0x6c9f558 != 0')
a('il2cpp_gc_has_strict_wbarriers', None, '', H, 'constant in source: return false (IL2CPP_ENABLE_STRICT_WRITE_BARRIERS off)')
a('il2cpp_gc_set_external_allocation_tracker', None, '', H, 'empty in source without IL2CPP_ENABLE_WRITE_BARRIER_VALIDATION; no-op stub')
a('il2cpp_gc_set_external_wbarrier_tracker', None, '', H, 'empty in source without IL2CPP_ENABLE_WRITE_BARRIER_VALIDATION; no-op stub')
a('il2cpp_gc_foreach_heap', None, '', L, 'GarbageCollector::ForEachHeapSection not located; stub')
a('il2cpp_gc_alloc_fixed', 0x42744c, 'il2cpp::gc::GarbageCollector::AllocateFixed', M, 'b 0x3dbf20; Domain::GetCurrent calls it as (0x38, NULL); wrapper passes (size, NULL)')
a('il2cpp_gc_free_fixed', 0x427450, 'il2cpp::gc::GarbageCollector::FreeFixed', M, 'b 0x3dbf30; adjacent to AllocateFixed 0x42744c as in BoehmGC.cpp (order only)')
a('il2cpp_gchandle_foreach_get_target', None, '', L, 'GCHandle::WalkStrongGCHandleTargets not located; stub')
a('il2cpp_object_header_size', None, '', H, 'constant: sizeof(Il2CppObject) = 16')
a('il2cpp_array_object_header_size', None, '', H, 'constant: kIl2CppSizeOfArray = offsetof(Il2CppArraySize, vector) = 32')
a('il2cpp_offset_of_array_length_in_array_object_header', None, '', H, 'constant: offsetof(Il2CppArray, max_length) = 24 (matches Array::GetLength in main)')
a('il2cpp_offset_of_array_bounds_in_array_object_header', None, '', H, 'constant: offsetof(Il2CppArray, bounds) = 16')
a('il2cpp_allocation_granularity', None, '', H, 'constant: 2*sizeof(void*) = 16')
a('il2cpp_method_get_declaring_type', 0x435438, 'il2cpp::vm::Method::GetClass (same body as GetDeclaringType)', M, 'Method::GetDeclaringType itself not emitted; source returns method->klass, identical to Method::GetClass 0x435438 (ldr x0,[x0,#0x20])')
a('il2cpp_method_get_flags', None, '', H, 'inline: if (iflags) *iflags = u16 @0x4e; return u16 @0x4c (flags offset verified by Method::IsInstance in main)')
a('il2cpp_method_get_token', 0x435444, 'il2cpp::vm::Method::GetToken', M, 'ldr w0,[x0,#0x48] (token; same offset il2cpp_custom_attrs_from_method reads), last fn of the Method.cpp range')
a('il2cpp_method_get_param_name', 0x4353cc, 'il2cpp::vm::Method::GetParamName', M, '(method,index): index<parameters_count, resolves generic definition, then metadata parameter-name lookup 0x3efde0; right after Method::GetParam')
a('il2cpp_property_get_flags', None, '', M, 'inline: ldr w0,[prop,#0x20] (PropertyInfo.attrs; struct layout from headers, 0x28 stride confirmed in Class::GetProperties)')
a('il2cpp_property_get_get_method', None, '', M, 'inline: ldr x0,[prop,#0x10] (PropertyInfo.get)')
a('il2cpp_property_get_set_method', None, '', M, 'inline: ldr x0,[prop,#0x18] (PropertyInfo.set)')
a('il2cpp_property_get_name', None, '', M, 'inline: ldr x0,[prop,#8] (PropertyInfo.name)')
a('il2cpp_property_get_parent', None, '', M, 'inline: ldr x0,[prop,#0] (PropertyInfo.parent)')
a('il2cpp_object_get_size', None, '', L, 'Object::GetSize not found in the Object.cpp range (0x406c40-0x407308); re-create from source (string/array/instance_size cases)')
a('il2cpp_value_box', 0x406c40, 'il2cpp::vm::Object::Box', H, 'target of the il2cpp_codegen Box wrapper 0x44c330 (16k generated call sites); returns *data for reference types, handles Nullable (bit3), allocates via 0x407060 and copies instance_size-0x10')
a('il2cpp_monitor_try_enter', 0x435850, 'il2cpp::vm::Monitor::TryEnter', H, 'target of Monitor::Enter (mov w1,#-1; b) and of the try_enter_with_atomic_var icall 0x466f2c')
a('il2cpp_monitor_pulse', 0x435e24, 'il2cpp::vm::Monitor::Pulse', H, 'mov w1,#0; b PulseMonitor 0x435e30; target of the Monitor_pulse icall 0x466ee4')
a('il2cpp_monitor_pulse_all', 0x435f7c, 'il2cpp::vm::Monitor::PulseAll', H, 'mov w1,#1; b PulseMonitor 0x435e30; target of the Monitor_pulse_all icall 0x466f08')
a('il2cpp_monitor_wait', None, '', H, 'Monitor::Wait not emitted; source = TryWait(obj, 0xFFFFFFFF) -> call 0x435f90')
a('il2cpp_monitor_try_wait', 0x435f90, 'il2cpp::vm::Monitor::TryWait', H, 'target of the Monitor_wait icall 0x466e78 (obj, ms)')
a('il2cpp_runtime_class_init', 0x46c400, 'il2cpp::vm::Runtime::ClassInit', H, 'early-out on klass->cctor_finished_or_no_cctor (0xe0), type-init lock, runs cctor; target of il2cpp_codegen_runtime_class_init 0x44c310 (74k generated call sites)')
a('il2cpp_runtime_object_init', 0x46eb48, 'il2cpp::vm::Runtime::ObjectInit', H, '1-arg twin of ObjectInitException (".ctor" lookup, InvokeWithThrow 0x46e524), placed right before it as in Runtime.cpp; 16 runtime callers')
a('il2cpp_string_new_utf16', 0x456994, 'il2cpp::vm::String::NewUtf16(const Il2CppChar*,int32_t)', H, '(text,len): allocates 2*len+0x1a, sets length @0x10, memcpy to chars @0x14; right after NewWrapper as in String.cpp; StringView overload is 0x456ae0')
a('il2cpp_string_is_interned', None, '', M, 'String::IsInterned not found after String::Intern 0x456b90; stub or re-create')
a('il2cpp_thread_get_all_attached_threads', None, '', L, 'Thread::GetAllAttachedThreads not located; stub')
a('il2cpp_is_vm_thread', None, '', L, 'Thread::IsVmThread not located; stub')
a('il2cpp_current_thread_walk_frame_stack', None, '', L, 'StackTrace::WalkFrameStack not located; stub')
a('il2cpp_thread_walk_frame_stack', None, '', L, 'StackTrace::WalkThreadFrameStack not located; stub')
a('il2cpp_current_thread_get_top_frame', None, '', L, 'StackTrace::GetTopStackFrame not located; stub')
a('il2cpp_thread_get_top_frame', None, '', L, 'StackTrace::GetThreadTopStackFrame not located; stub')
a('il2cpp_current_thread_get_frame_at', None, '', L, 'StackTrace::GetStackFrameAt not located; stub')
a('il2cpp_thread_get_frame_at', None, '', L, 'StackTrace::GetThreadStackFrameAt not located; stub')
a('il2cpp_current_thread_get_stack_depth', None, '', L, 'StackTrace::GetStackDepth not located; stub')
a('il2cpp_thread_get_stack_depth', None, '', L, 'StackTrace::GetThreadStackDepth not located; stub')
a('il2cpp_override_stack_backtrace', None, '', L, 'os::StackTrace::OverrideStackBacktrace not located; stub')
a('il2cpp_type_get_reflection_name', None, '', H, 'no wrapper; re-create exactly like il2cpp_type_get_name 0x465aa0 with format 1: Type::GetName 0x443288 + Memory::Malloc 0x419620')
a('il2cpp_type_is_pointer_type', None, '', H, 'inline in source: type->type (byte @0xa) == IL2CPP_TYPE_PTR 0x0f')
a('il2cpp_image_get_assembly', None, '', M, 'inline: ldr x0,[image,#0x10] (assembly; offset from headers, neighbours name@0/typeCount@0x18 verified)')
a('il2cpp_image_get_name', None, '', H, 'inline: ldr x0,[image,#0] (name)')
a('il2cpp_image_get_filename', None, '', H, 'inline: same as il2cpp_image_get_name (source returns image->name)')
a('il2cpp_image_get_entry_point', None, '', L, 'MetadataCache::GetAssemblyEntryPoint not located; stub returning NULL')
a('il2cpp_capture_memory_snapshot', None, '', L, 'MemoryInformation::CaptureManagedMemorySnapshot not located; stub')
a('il2cpp_free_captured_memory_snapshot', None, '', L, 'MemoryInformation::FreeCapturedManagedMemorySnapshot not located; stub')
a('il2cpp_register_log_callback', None, '', L, 'utils::Logging::SetLogCallback not located; stub')
a('il2cpp_is_debugger_attached', None, '', H, 'constant false without IL2CPP_MONO_DEBUGGER (il2cpp_debugger_set_agent_options is an empty ret in main)')
a('il2cpp_register_debugger_agent_transport', None, '', H, 'empty in source without IL2CPP_MONO_DEBUGGER; no-op stub')
a('il2cpp_debug_get_method_info', None, '', H, 'source returns false unless IL2CPP_ENABLE_NATIVE_STACKTRACES (not defined for Switch); stub false')
a('il2cpp_custom_attrs_from_field', None, '', H, 'inline: MetadataCache::GetCustomAttributeTypeToken 0x3f4234 with (field->parent(0x10)->image, field->token(0x1c)); same shape as from_class/from_method wrappers')
a('il2cpp_set_default_thread_affinity', None, '', L, 'Thread::SetDefaultAffinityMask not located; stub')
a('il2cpp_class_for_each', None, '', L, 'MemoryInformation::ReportIL2CppClasses not located; stub')
a('il2cpp_unity_set_android_network_up_state_func', None, '', H, 'Android-only (AndroidRuntime); no counterpart; no-op stub')

# extra runtime symbols identified along the way: addr -> (name, confidence, evidence)
R = {
    0x46ce20: ('il2cpp::vm::Runtime::Init', H, 'called by il2cpp_init; refs "mscorlib.dll"'),
    0x46e258: ('il2cpp::vm::Runtime::IsShuttingDown', M, 'returns byte global; Runtime.cpp order after Shutdown'),
    0x46e264: ('il2cpp::vm::Runtime::SetConfigDir', H, 'il2cpp_set_config_dir target'),
    0x46e278: ('il2cpp::vm::Runtime::SetConfig', H, 'il2cpp_set_config target'),
    0x46e33c: ('il2cpp::vm::Runtime::SetUnityTlsInterface', H, 'il2cpp_unity_install_unitytls_interface target'),
    0x46e348: ('il2cpp::vm::Runtime::GetFrameworkVersion', L, 'Runtime.cpp order only'),
    0x46e354: ('il2cpp::vm::Runtime::GetConfigDir', M, 'returns std::string built from the config-dir global 0x6ca2488'),
    0x46e408: ('il2cpp::vm::Runtime::GetUnityTlsInterface', H, 'loads the global SetUnityTlsInterface stores (0x6ca2440)'),
    0x46e414: ('il2cpp::vm::Runtime::GetDelegateInvoke', H, 'GetMethodFromName(klass,"Invoke",-1)'),
    0x46e424: ('il2cpp::vm::Runtime::DelegateInvoke', M, 'looks up "Invoke" on delegate class then Invoke; Runtime.cpp order'),
    0x46e470: ('il2cpp::vm::Runtime::Invoke', H, 'il2cpp_runtime_invoke target'),
    0x46e524: ('il2cpp::vm::Runtime::InvokeWithThrow', H, 'called by Invoke/ObjectInit; Runtime.cpp order'),
    0x46e678: ('il2cpp::vm::Runtime::InvokeArray', M, 'Runtime.cpp order; takes Il2CppArray params'),
    0x46e700: ('il2cpp::vm::Runtime::InvokeConvertArgs', H, 'il2cpp_runtime_invoke_convert_args target'),
    0x46ebdc: ('il2cpp::vm::Runtime::ObjectInitException', H, 'il2cpp_runtime_object_init_exception target'),
    0x46ec44: ('il2cpp::vm::Runtime::SetUnhandledExceptionPolicy', H, 'il2cpp_runtime_unhandled_exception_policy_set target'),
    0x46ed20: ('il2cpp::vm::Runtime::CreateUnhandledExceptionEventArgs', M, 'called by UnhandledException; refs "System" + class name'),
    0x46edf8: ('il2cpp::vm::Runtime::SetExitCode', M, 'stores w0 to global; called by Environment::Exit icall before Shutdown'),
    0x46b320: ('il2cpp::icalls::mscorlib::System::Environment::Exit', H, 'target of managed System.Environment::Exit; SetExitCode, Shutdown, exit'),
    0x403e04: ('il2cpp::utils::Runtime::SetDataDir', H, 'il2cpp_set_data_dir target'),
    0x403e20: ('il2cpp::utils::Runtime::GetDataDir', H, 'returns the data-dir global 0x6ca0048 or default "Data"; used by metadata file loader 0x46cb24 ("Metadata")'),
    0x459af0: ('il2cpp::utils::Environment::SetMainArgs(const char* const*, int)', H, 'il2cpp_set_commandline_arguments target'),
    0x4195fc: ('il2cpp::utils::Memory::SetMemoryCallbacks', H, 'il2cpp_set_memory_callbacks target'),
    0x419638: ('il2cpp::utils::Memory::Free', H, 'il2cpp_free target'),
    0x43eb18: ('il2cpp::vm::Image::GetCorlib', H, 'il2cpp_get_corlib target'),
    0x43eeb0: ('il2cpp::vm::Image::ClassFromName', H, 'target of Class::FromName'),
    0x43f4e0: ('il2cpp::vm::Image::GetNumTypes', H, 'il2cpp_image_get_class_count callee'),
    0x43f4e8: ('il2cpp::vm::Image::GetType', H, 'il2cpp_image_get_class target'),
    0x41e974: ('il2cpp::vm::InternalCalls::Add', H, 'given anchor'),
    0x3ec6a4: ('il2cpp::vm::Class::FromIl2CppType', H, 'il2cpp_class_from_il2cpp_type/from_type target (throwOnError=true)'),
    0x3ec7d0: ('il2cpp::vm::Class::FromIl2CppTypeEnum', H, 'first callee of FromIl2CppType with the type enum; jump table over IL2CPP_TYPE_*'),
    0x3ec934: ('il2cpp::vm::Class::GetBoundedArrayClass', H, 'il2cpp_bounded_array_class_get target'),
    0x45c270: ('il2cpp::metadata::ArrayMetadata::GetBoundedArrayClass', M, 'target of Class::GetArrayClass/GetBoundedArrayClass'),
    0x3ec938: ('il2cpp::vm::Class::GetPtrClass(const Il2CppType*)', M, 'FromIl2CppType then b GetPtrClass(Il2CppClass*) 0x3f0cb0'),
    0x3f0cb0: ('il2cpp::vm::Class::GetPtrClass(Il2CppClass*)', M, 'see 0x3ec938'),
    0x3ec950: ('il2cpp::vm::Class::GetArrayClass', H, 'il2cpp_array_class_get target'),
    0x3ecc7c: ('il2cpp::vm::Class::FromSystemType', H, 'il2cpp_class_from_system_type target'),
    0x3eccb0: ('il2cpp::vm::Class::Init', H, 'early-out on initialized bit; called by FromSystemType, Object::New, Array::NewSpecific'),
    0x3ed09c: ('il2cpp::vm::Class::GetEnumBaseType', H, 'il2cpp_class_enum_basetype target'),
    0x3ed140: ('il2cpp::vm::Class::SetupEvents', M, 'early-out on klass->events(0x88)'),
    0x3ed2bc: ('il2cpp::vm::Class::GetFields', H, 'il2cpp_class_get_fields target'),
    0x3ed340: ('il2cpp::vm::Class::SetupFields', M, 'early-out on size_inited bit8; called from GetFields/GetValueSize'),
    0x3ed4b0: ('il2cpp::vm::Class::GetFieldFromName', H, 'il2cpp_class_get_field_from_name target'),
    0x3ed560: ('il2cpp::vm::Class::GetFinalizer', L, 'Class.cpp order only'),
    0x3ed5b8: ('il2cpp::vm::Class::GetInstanceSize', H, 'il2cpp_class_instance_size target'),
    0x3ed650: ('il2cpp::vm::Class::SetupInterfaces', M, 'early-out on implementedInterfaces(0xa8); called by IsSubclassOf'),
    0x3ed7b4: ('il2cpp::vm::Class::GetMethods', H, 'il2cpp_class_get_methods target'),
    0x3ed840: ('il2cpp::vm::Class::SetupMethods', M, 'Class.cpp order; checks method_count(0x120)'),
    0x3ed9d0: ('il2cpp::vm::Class::GetMethodFromNameFlags', H, 'target of GetMethodFromName with flags=0'),
    0x3edb70: ('il2cpp::vm::Class::GetMethodFromNameFlagsAndSig', M, '5 args; Class.cpp order'),
    0x3eddec: ('il2cpp::vm::Class::GetName', H, 'il2cpp_class_get_name target'),
    0x3eddf4: ('il2cpp::vm::Class::GetNamespace', H, 'il2cpp_class_get_namespace target'),
    0x3eddfc: ('il2cpp::vm::Class::GetNestedTypes', H, 'il2cpp_class_get_nested_types target'),
    0x3ede90: ('il2cpp::vm::Class::SetupNestedTypes', L, 'Class.cpp order only'),
    0x3ee090: ('il2cpp::vm::Class::GetParent', H, 'il2cpp_class_get_parent target'),
    0x3ee120: ('il2cpp::vm::Class::SetupProperties', M, 'early-out on klass->properties(0x90)'),
    0x3ee3dc: ('il2cpp::vm::Class::SetClassInitializationError', M, 'GCHandle::New(error,false) stored to klass+0xd8'),
    0x3ee434: ('il2cpp::vm::Class::HasParent', H, 'il2cpp_class_has_parent target'),
    0x3ee4a0: ('il2cpp::vm::Class::SetupTypeHierarchy', M, 'early-out on typeHierarchy(0xc8); called by HasParent/IsSubclassOf'),
    0x3ee894: ('il2cpp::vm::Class::IsAssignableFrom(Il2CppReflectionType*,Il2CppReflectionType*)', H, 'target of the type_is_assignable_from icall 0x42ede8'),
    0x3ee90c: ('il2cpp::vm::Class::IsGeneric', H, 'il2cpp_class_is_generic target'),
    0x3ee91c: ('il2cpp::vm::Class::IsInflated', H, 'il2cpp_class_is_inflated target'),
    0x3ee930: ('il2cpp::vm::Class::IsSubclassOf', H, 'il2cpp_class_is_subclass_of target'),
    0x3f04e8: ('il2cpp::vm::Class::FromName', H, 'il2cpp_class_from_name target'),
    0x3f0898: ('il2cpp::vm::Class::GetArrayElementSize', H, 'il2cpp_class_array_element_size target'),
    0x3f0fd0: ('il2cpp::vm::Class::HasAttribute', H, 'il2cpp_class_has_attribute target'),
    0x3f0fd4: ('il2cpp::vm::Class::GetImage', H, 'il2cpp_class_get_image target'),
    0x3f0fdc: ('il2cpp::vm::Class::GetGenericContainer', M, 'ldr x0,[x0,#0xf0]; Class.cpp order'),
    0x3f0ff0: ('il2cpp::vm::Class::GetCCtor', M, 'checks has_cctor bit10; Class.cpp order'),
    0x3f10c4: ('il2cpp::vm::Class::GetFieldDefaultValue', M, 'b 0x432b44; called by Field::GetValueObject/StaticGetValueInternal for literal fields'),
    0x3f131c: ('il2cpp::vm::Class::GetStaticFieldData', M, 'returns address of global dynamic_array 0x6c9fb10; called by Liveness::FromStatics'),
    0x3f14ac: ('il2cpp::vm::Class::GetAssemblyNameNoExtension', H, 'il2cpp_class_get_assemblyname target'),
    0x3f1674: ('il2cpp::vm::Class::GetDeclaringType', H, 'il2cpp_class_get_declaring_type target'),
    0x3f1680: ('il2cpp::vm::Class::GetVirtualMethod', M, 'same vtable/interface lookup as Object::GetVirtualMethod but on a klass; last in Class.cpp order'),
    0x405fac: ('il2cpp::vm::Array::GetElementSize', H, 'il2cpp_array_element_size target'),
    0x405fb4: ('il2cpp::vm::Array::GetLength', H, 'il2cpp_array_length target'),
    0x405fc0: ('il2cpp::vm::Array::NewFull', H, 'il2cpp_array_new_full target'),
    0x406360: ('il2cpp::vm::Array::GetFirstElementAddress', M, 'add x0,x0,#0x20'),
    0x406490: ('il2cpp::vm::Array::New', H, 'il2cpp_array_new target'),
    0x4064c0: ('il2cpp::vm::Array::NewSpecific', H, 'il2cpp_array_new_specific target'),
    0x406780: ('il2cpp::vm::Assembly::GetImage', H, 'il2cpp_assembly_get_image target'),
    0x406900: ('il2cpp::vm::Assembly::Load', H, 'il2cpp_domain_assembly_open target'),
    0x431f9c: ('il2cpp::vm::Domain::GetCurrent', H, 'il2cpp_domain_get target'),
    0x432000: ('il2cpp::vm::Domain::GetRoot', M, 'called right after GetCurrent in Runtime::UnhandledException'),
    0x41ce38: ('il2cpp::vm::Exception::Raise(Il2CppException*, MethodInfo*)', H, 'il2cpp_raise_exception callee; noreturn; 151 runtime callers'),
    0x41dc84: ('il2cpp::vm::Exception::FromNameMsg', H, 'il2cpp_exception_from_name_msg target'),
    0x41dde0: ('il2cpp::vm::Exception::GetArgumentNullException', H, 'il2cpp_get_exception_argument_null target'),
    0x41dd78: ('il2cpp::vm::Exception::GetArgumentException', M, 'called with ("lockTaken","lockTaken must be false") by the try_enter icall'),
    0x46bfa0: ('il2cpp::vm::Field::GetName', H, 'il2cpp_field_get_name target'),
    0x46bfa8: ('il2cpp::vm::Field::GetParent', H, 'il2cpp_field_get_parent target'),
    0x46bfb0: ('il2cpp::vm::Field::GetFlags', H, 'il2cpp_field_get_flags target'),
    0x46bfbc: ('il2cpp::vm::Field::GetOffset', H, 'il2cpp_field_get_offset target'),
    0x46bfc4: ('il2cpp::vm::Field::GetValue', H, 'il2cpp_field_get_value target'),
    0x46bfe0: ('il2cpp::vm::Field::SetValueRaw', H, '(type,dest,value,deref_pointer); shared callee of Field::GetValue/SetValue'),
    0x46c2a8: ('il2cpp::vm::Field::GetToken', M, 'ldr w0,[x0,#0x1c]; Field.cpp order'),
    0x46c93c: ('il2cpp::vm::Field::GetType', H, 'il2cpp_field_get_type target'),
    0x46c944: ('il2cpp::vm::Field::HasAttribute', H, 'il2cpp_field_has_attribute target'),
    0x46c948: ('il2cpp::vm::Field::IsDeleted', L, 'returns false; Field.cpp order only'),
    0x46c970: ('il2cpp::vm::Field::StaticGetValueInternal', M, '(field,value,thread); target of StaticGetValue'),
    0x46ca8c: ('il2cpp::vm::Field::IsInstance', M, '!(attrs & STATIC); Field.cpp order'),
    0x46caa0: ('il2cpp::vm::Field::IsNormalStatic', M, 'Field.cpp order'),
    0x46cacc: ('il2cpp::vm::Field::IsThreadStatic', M, 'Field.cpp order'),
    0x46cb00: ('il2cpp::vm::Field::GetInstanceFieldDataPointer', M, 'instance + offset (-0x10 for value types); Field.cpp order'),
    0x40b414: ('il2cpp::vm::Reflection::HasAttribute(FieldInfo*, Il2CppClass*)', H, 'target of Field::HasAttribute'),
    0x40b464: ('il2cpp::vm::Reflection::HasAttribute(const MethodInfo*, Il2CppClass*)', H, 'target of Method::HasAttribute'),
    0x40b4b4: ('il2cpp::vm::Reflection::HasAttribute(Il2CppClass*, Il2CppClass*)', H, 'target of Class::HasAttribute'),
    0x40b4fc: ('il2cpp::vm::Reflection::HasAttribute(Il2CppMetadataCustomAttributeHandle, Il2CppClass*)', H, 'il2cpp_custom_attrs_has_attr target'),
    0x40aa58: ('il2cpp::vm::Reflection::GetCustomAttribute', H, 'il2cpp_custom_attrs_get_attr target'),
    0x40ac58: ('il2cpp::vm::Reflection::ConstructCustomAttributes', H, 'il2cpp_custom_attrs_construct target'),
    0x408c2c: ('il2cpp::vm::Reflection::GetMethod', H, 'il2cpp_method_get_from_reflection target'),
    0x408c34: ('il2cpp::vm::Reflection::GetMethodObject', H, 'il2cpp_method_get_object target'),
    0x4089f8: ('il2cpp::vm::Reflection::GetTypeObject', H, 'il2cpp_type_get_object target'),
    0x3f4234: ('il2cpp::vm::MetadataCache::GetCustomAttributeTypeToken', H, 'target of the inline custom_attrs_from_class/method wrappers (b 0x433d8c)'),
    0x3f4254: ('il2cpp::vm::MetadataCache::InitializeRuntimeMetadata', M, 'callee of il2cpp_codegen_initialize_runtime_metadata 0x44c0d0'),
    0x42719c: ('il2cpp::gc::GarbageCollector::Collect', H, 'il2cpp_gc_collect target'),
    0x4271a0: ('il2cpp::gc::GarbageCollector::CollectALittle', H, 'il2cpp_gc_collect_a_little target'),
    0x4271a4: ('il2cpp::gc::GarbageCollector::StartIncrementalCollection', H, 'il2cpp_gc_start_incremental_collection target'),
    0x4271a8: ('il2cpp::gc::GarbageCollector::SetWriteBarrier', H, 'b 0x3dbec0; target of Il2CppCodeGenWriteBarrier 0x44c010 (87k call sites)'),
    0x4271ac: ('il2cpp::gc::GarbageCollector::GetUsedHeapSize', H, 'il2cpp_gc_get_used_size target'),
    0x4271d4: ('il2cpp::gc::GarbageCollector::GetAllocatedHeapSize', H, 'il2cpp_gc_get_heap_size target'),
    0x4271d8: ('il2cpp::gc::GarbageCollector::Disable', H, 'il2cpp_gc_disable target'),
    0x4271dc: ('il2cpp::gc::GarbageCollector::Enable', H, 'il2cpp_gc_enable target'),
    0x4271e0: ('il2cpp::gc::GarbageCollector::SetMode', H, 'il2cpp_gc_set_mode target'),
    0x4273a8: ('il2cpp::gc::GarbageCollector::RegisterThread', M, 'GC_get_stack_base/GC_register_my_thread; called by Thread::Attach'),
    0x4273e0: ('il2cpp::gc::GarbageCollector::UnregisterThread', M, 'called by Thread::Detach'),
    0x427444: ('il2cpp::gc::GarbageCollector::StopWorld', H, 'il2cpp_stop_gc_world target'),
    0x427448: ('il2cpp::gc::GarbageCollector::StartWorld', H, 'il2cpp_start_gc_world target'),
    0x427454: ('il2cpp::gc::GarbageCollector::GetMaxTimeSliceNs', H, 'il2cpp_gc_get_max_time_slice_ns target'),
    0x427458: ('il2cpp::gc::GarbageCollector::SetMaxTimeSliceNs', H, 'il2cpp_gc_set_max_time_slice_ns target'),
    0x42745c: ('il2cpp::gc::GarbageCollector::IsIncremental', H, 'il2cpp_gc_is_incremental target'),
    0x427524: ('il2cpp::gc::GCHandle::New', H, 'il2cpp_gchandle_new target'),
    0x427a44: ('il2cpp::gc::GCHandle::NewWeakref', H, 'il2cpp_gchandle_new_weakref callee'),
    0x427b10: ('il2cpp::gc::GCHandle::GetTarget', H, 'il2cpp_gchandle_get_target target'),
    0x427d50: ('il2cpp::gc::GCHandle::Free', H, 'il2cpp_gchandle_free target'),
    0x429170: ('il2cpp::gc::WriteBarrier::GenericStore', H, 'il2cpp_gc_wbarrier_set_field target'),
    0x3daeb0: ('GC_gcollect', M, 'bdwgc; target of GarbageCollector::Collect'),
    0x3d8240: ('GC_collect_a_little', M, 'bdwgc; target of CollectALittle'),
    0x3d81a0: ('GC_start_incremental_collection', M, 'bdwgc (Unity fork)'),
    0x3e2210: ('GC_enable', H, 'bdwgc; GC_dont_gc--'),
    0x3e2270: ('GC_disable', H, 'bdwgc; GC_dont_gc++'),
    0x3e1d60: ('GC_get_heap_size', M, 'bdwgc; target of GetAllocatedHeapSize'),
    0x3e1d70: ('GC_get_free_bytes', M, 'bdwgc; subtracted in GetUsedHeapSize'),
    0x3e2450: ('GC_stop_world_external', M, 'bdwgc; target of StopWorld'),
    0x3e2470: ('GC_start_world_external', M, 'bdwgc; target of StartWorld'),
    0x3e2440: ('GC_get_time_limit_ns', M, 'bdwgc (Unity fork); target of GetMaxTimeSliceNs'),
    0x3e2430: ('GC_set_time_limit_ns', M, 'bdwgc (Unity fork); target of SetMaxTimeSliceNs'),
    0x3d80b0: ('GC_is_incremental_mode', M, 'bdwgc; callee of IsIncremental'),
    0x3dbec0: ('GC_dirty (write-barrier hook)', M, 'bdwgc; target of SetWriteBarrier/GenericStore'),
    0x3dbf20: ('GC_malloc_uncollectable', M, 'bdwgc; target of AllocateFixed'),
    0x3dbf30: ('GC_free', M, 'bdwgc; target of FreeFixed'),
    0x41fa88: ('il2cpp::vm::Liveness::AllocateStruct', H, 'il2cpp_unity_liveness_allocate_struct target'),
    0x41fbf0: ('il2cpp::vm::Liveness::FromRoot', H, 'il2cpp_unity_liveness_calculation_from_root target'),
    0x41fca0: ('il2cpp::vm::Liveness::FromStatics', H, 'il2cpp_unity_liveness_calculation_from_statics target'),
    0x41fb30: ('il2cpp::vm::Liveness::Finalize', H, 'il2cpp_unity_liveness_finalize target'),
    0x41fafc: ('il2cpp::vm::Liveness::FreeStruct', H, 'il2cpp_unity_liveness_free_struct target'),
    0x43516c: ('il2cpp::vm::Method::GetReturnType', H, 'il2cpp_method_get_return_type target'),
    0x435174: ('il2cpp::vm::Method::GetName', H, 'il2cpp_method_get_name target'),
    0x4352e4: ('il2cpp::vm::Method::IsGeneric', H, 'il2cpp_method_is_generic target'),
    0x4352f0: ('il2cpp::vm::Method::IsInflated', H, 'il2cpp_method_is_inflated target'),
    0x4352fc: ('il2cpp::vm::Method::IsGenericInstance', M, 'is_inflated && !is_generic && genericMethod->context.method_inst; il2cpp_codegen wrapper 0x44c250'),
    0x435394: ('il2cpp::vm::Method::IsInstance', H, 'il2cpp_method_is_instance target'),
    0x4353a4: ('il2cpp::vm::Method::GetParamCount', H, 'il2cpp_method_get_param_count target'),
    0x4353ac: ('il2cpp::vm::Method::GetParam', H, 'il2cpp_method_get_param target'),
    0x435438: ('il2cpp::vm::Method::GetClass', H, 'il2cpp_method_get_class target'),
    0x435440: ('il2cpp::vm::Method::HasAttribute', H, 'il2cpp_method_has_attribute target'),
    0x435848: ('il2cpp::vm::Monitor::Enter', H, 'il2cpp_monitor_enter target; also target of the Monitor::Enter icall 0x466e9c'),
    0x435cb0: ('il2cpp::vm::Monitor::Exit', H, 'il2cpp_monitor_exit target; also target of the Monitor::Exit icall 0x466ec0'),
    0x435e30: ('il2cpp::vm::PulseMonitor (static)', H, 'shared callee of Pulse/PulseAll with all=false/true'),
    0x4362cc: ('il2cpp::vm::Monitor::IsAcquired', M, 'target of the Monitor_test_synchronised icall 0x466e54'),
    0x406c40: ('il2cpp::vm::Object::Box', H, 'see il2cpp_value_box'),
    0x406d34: ('il2cpp::vm::Object::New', H, 'il2cpp_object_new callee; il2cpp_codegen_object_new 0x44c4a0 (62k call sites)'),
    0x407060: ('il2cpp::vm::Object::NewAllocSpecific', M, 'target of Object::New and NewPinned 0x407188'),
    0x406d40: ('il2cpp::vm::Object::Clone', M, 'Object.cpp order (between Box and GetClass)'),
    0x406e2c: ('il2cpp::vm::Object::GetClass', H, 'il2cpp_object_get_class target'),
    0x406e34: ('il2cpp::vm::Object::GetHash', M, 'pointer hash with golden-ratio multiply; Object.cpp order'),
    0x406e50: ('il2cpp::vm::Object::GetVirtualMethod', H, 'il2cpp_object_get_virtual_method target'),
    0x406f44: ('il2cpp::vm::Object::IsInst', H, 'il2cpp_codegen IsInst wrapper 0x44c320 (19k call sites); Object.cpp order'),
    0x40718c: ('il2cpp::vm::Object::Unbox', H, 'il2cpp_object_unbox target'),
    0x407194: ('il2cpp::vm::Object::UnboxNullable', M, 'Object.cpp order'),
    0x40720c: ('il2cpp::vm::Object::UnboxNullableWithWriteBarrier', M, 'Object.cpp order; tail-called by SetValueInternal icall'),
    0x407308: ('il2cpp::vm::PlatformInvoke::SetFindPluginCallback', H, 'il2cpp_set_find_plugin_callback target'),
    0x447048: ('il2cpp::os::LibraryLoader::SetFindPluginCallback', H, 'stores callback to global 0x6ca17d8'),
    0x45a78c: ('il2cpp::utils::StringUtils::GetLength', H, 'il2cpp_string_length target'),
    0x45a784: ('il2cpp::utils::StringUtils::GetChars', H, 'il2cpp_string_chars target'),
    0x45683c: ('il2cpp::vm::String::New', H, 'il2cpp_string_new target'),
    0x45696c: ('il2cpp::vm::String::NewWrapper', H, 'il2cpp_string_new_wrapper target'),
    0x456864: ('il2cpp::vm::String::NewLen', H, 'il2cpp_string_new_len target'),
    0x456a44: ('il2cpp::vm::String::NewSize', H, '(len): allocates string of len chars; String.cpp order'),
    0x456ae0: ('il2cpp::vm::String::NewUtf16(const StringView<Il2CppChar>&)', H, 'loads (ptr,len) pair from x0; String.cpp order'),
    0x456b90: ('il2cpp::vm::String::Intern', H, 'il2cpp_string_intern target'),
    0x456784: ('il2cpp::vm::String::Empty', M, 'returns global 0x6ca1be0 that NewUtf16 returns for len 0'),
    0x4320f8: ('il2cpp::vm::Thread::Current', H, 'il2cpp_thread_current target'),
    0x436484: ('il2cpp::vm::Thread::Attach', H, 'il2cpp_thread_attach target'),
    0x436580: ('il2cpp::vm::Thread::Detach(Il2CppThread*)', H, 'il2cpp_thread_detach target'),
    0x442930: ('il2cpp::vm::Type::GetType', H, 'il2cpp_type_get_type target'),
    0x4432dc: ('il2cpp::vm::Type::GetClassOrElementClass', H, 'il2cpp_type_get_class_or_element_class target'),
    0x443288: ('il2cpp::vm::Type::GetName(const Il2CppType*, Il2CppTypeNameFormat)', H, 'callee of il2cpp_type_get_name (format 0) / assembly_qualified_name (format 3); returns std::string via x8'),
    0x443584: ('il2cpp::vm::Type::IsEqualToType', H, 'il2cpp_type_equals target (b 0x45e0ac)'),
    0x44c010: ('Il2CppCodeGenWriteBarrier', H, 'il2cpp-codegen; b GarbageCollector::SetWriteBarrier; 87k call sites'),
    0x44c070: ('il2cpp_codegen_resolve_icall', H, 'given anchor'),
    0x44c0c0: ('il2cpp_codegen_register', H, 'given anchor'),
    0x44c0d0: ('il2cpp_codegen_initialize_runtime_metadata', M, '188k call sites from generated code; calls 0x3f4254'),
    0x44c0f0: ('il2cpp_codegen_initialize_runtime_metadata_inline', L, 'b 0x3f4254; 60k call sites; exact codegen name inferred'),
    0x44c2f0: ('il2cpp_codegen_raise_exception', H, 'clears ex fields then Exception::Raise; 26k call sites, noreturn'),
    0x44c310: ('il2cpp_codegen_runtime_class_init', H, 'b Runtime::ClassInit'),
    0x44c320: ('IsInst (il2cpp-codegen)', H, 'b Object::IsInst'),
    0x44c330: ('Box (il2cpp-codegen)', H, 'b Object::Box'),
    0x44c340: ('UnBox (il2cpp-codegen)', M, 'b Object::Unbox'),
    0x44c4a0: ('il2cpp_codegen_object_new', H, 'b Object::New'),
    0x44c230: ('SZArrayNew (il2cpp-codegen)', M, 'zero-extends length; b Array::NewSpecific'),
    0x44c900: ('il2cpp_codegen_class_is_assignable_from', H, 'b Class::IsAssignableFrom'),
    0x44c910: ('il2cpp_codegen_class_from_type', M, 'mov w1,#1; b Class::FromIl2CppType'),
    0x466e54: ('il2cpp::icalls::mscorlib::System::Threading::Monitor::Monitor_test_synchronised', H, 'target of the managed method'),
    0x466e78: ('il2cpp::icalls::mscorlib::System::Threading::Monitor::Monitor_wait', H, 'target of the managed method'),
    0x466e9c: ('il2cpp::icalls::mscorlib::System::Threading::Monitor::Enter', H, 'target of the managed method'),
    0x466ec0: ('il2cpp::icalls::mscorlib::System::Threading::Monitor::Exit', H, 'target of the managed method'),
    0x466ee4: ('il2cpp::icalls::mscorlib::System::Threading::Monitor::Monitor_pulse', H, 'target of the managed method'),
    0x466f08: ('il2cpp::icalls::mscorlib::System::Threading::Monitor::Monitor_pulse_all', H, 'target of the managed method'),
    0x466f2c: ('il2cpp::icalls::mscorlib::System::Threading::Monitor::try_enter_with_atomic_var', H, 'target of the managed method'),
    0x46b44c: ('il2cpp::icalls::mscorlib::System::String::InternalIntern', H, 'target of managed System.String::Intern/InternalIntern; b il2cpp_string_intern'),
}


def main():
    h = open(HDR).read()
    api = re.findall(r'^\s*DO_API(?:_NO_RETURN)?\((.*?),\s*(il2cpp_\w+)\s*,\s*(\(.*\))\);', h, re.M)
    api = [(r.strip(), n, p) for r, n, p in api if 'profiler' not in n]
    assert len(api) == 232
    use = {}
    for l in open(OUT + r'\up_users.tsv').read().split('\n')[1:]:
        p = l.split('\t')
        if len(p) > 4:
            kinds = eval(p[3])
            real = sum(v for k, v in kinds.items() if k in ('call', 'jmp', 'load', 'cmp'))
            use[p[0]] = (int(p[1]), real, p[4] if real else '')
    rows = []
    for r, n, p in api:
        proto = '%s %s%s' % (r, n, p)
        bo, nu, users = use[n]
        users = ' | '.join(re.sub(r'^\?+(\w+)@.*? x(\d+)$', r'\1 x\2', u) for u in users.split(' | ')[:4]) if users else ''
        if n in W:
            ad, conf, ev = W[n]
            rows.append((n, '%#x' % ad, conf, ev, proto, 'present', '', '', bo, nu, users))
        else:
            va, vn, conf, note = A[n]
            rows.append((n, '', conf, 'NO WRAPPER IN main (all 135 functions of the il2cpp-api.cpp range 0x4652c0-0x465d28 are assigned to other names). ' + note, proto,
                         'absent', '%#x' % va if va else '', vn, bo, nu, users))
    assert not (set(A) & set(W)) and len(rows) == 232
    with open(OUT + r'\il2cpp_api_map.tsv', 'w', encoding='utf-8', newline='\n') as f:
        f.write('name\taddress\tconfidence\tevidence\tprototype\tstatus\tvm_target_address\tvm_target_name\twin_bind_order\twin_player_refs\twin_player_users\n')
        for x in rows:
            f.write('\t'.join(str(c) for c in x) + '\n')
    # runtime symbols
    rs = dict(R)
    for n, (va, vn, conf, note) in A.items():
        if va and va not in rs:
            rs[va] = (vn, conf, 'underlying function for absent ' + n + ': ' + note)
    for n, (ad, conf, ev) in W.items():
        rs[ad] = (n, conf, 'il2cpp-api.cpp wrapper: ' + ev)
    with open(OUT + r'\runtime_symbols.tsv', 'w', encoding='utf-8', newline='\n') as f:
        f.write('address\tname\tconfidence\tevidence\n')
        for ad in sorted(rs):
            f.write('%#x\t%s\t%s\t%s\n' % ((ad,) + rs[ad]))
    import collections
    print('present by confidence', collections.Counter(x[2] for x in rows if x[5] == 'present'))
    print('absent: total', sum(1 for x in rows if x[5] == 'absent'), 'with vm target', sum(1 for x in rows if x[5] == 'absent' and x[6]),
          'by vm-id confidence', collections.Counter(x[2] for x in rows if x[5] == 'absent' and x[6]))
    print('absent & used by Windows player:', [(x[0], x[9], x[10]) for x in rows if x[5] == 'absent' and x[9]])
    print('present & unused by Windows player:', [x[0] for x in rows if x[5] == 'present' and not x[9]])
    print('runtime symbols', len(rs), collections.Counter(v[1] for v in rs.values()))
    print('absent without vm target:', ' '.join(x[0] for x in rows if x[5] == 'absent' and not x[6]))


if __name__ == '__main__':
    main()
