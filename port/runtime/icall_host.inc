// {icall name, host function}. Included by icall_host.c.
// UnityEngine.Switch.Performance: PerformanceMode 0 = Normal (handheld), 1 = Boost (docked).
{"UnityEngine.Switch.Performance::GetMode_Internal", ret1},
{"UnityEngine.Switch.Notification::EnterExitRequestHandlingSection_Internal", nop},
{"UnityEngine.Switch.Notification::LeaveExitRequestHandlingSection_Internal", nop},
{"UnityEngine.Switch.Notification::GetCurrentFocusState_Internal", ret1},   // FocusState.InFocus
{"UnityEngine.Switch.Notification::SetFocusHandlingMode_Internal", nop},
{"UnityEngine.Switch.Notification::SetOperationModeChangedNotificationEnabled_Internal", nop},
{"UnityEngine.Switch.Notification::SetPerformanceModeChangedNotificationEnabled_Internal", nop},
{"UnityEngine.Switch.Notification::SetResumeNotificationEnabled_Internal", nop},
{"UnityEngine.Switch.Applet::Begin", nop},
{"UnityEngine.Switch.Applet::End", nop},
// UnityEngine.Switch.NetworkInterfaceWrapper (nn::nifm): there is no network, a connection request finishes at once
// and is not accepted.
{"UnityEngine.Switch.NetworkInterfaceWrapper::EnterNetworkConnecting", ret0},
{"UnityEngine.Switch.NetworkInterfaceWrapper::WeakEnterNetworkConnecting", ret0},
{"UnityEngine.Switch.NetworkInterfaceWrapper::LeaveNetworkConnecting", nop},
{"UnityEngine.Switch.NetworkInterfaceWrapper::WaitForNetworkConnecting", nop},
{"UnityEngine.Switch.NetworkInterfaceWrapper::GetNetworkReferenceCount", ret0},
{"UnityEngine.Switch.NetworkInterfaceWrapper::IsNetworkAccepted", ret0},
{"UnityEngine.Switch.NetworkInterfaceWrapper::IsNetworkAvailable", ret0},
{"UnityEngine.Switch.NetworkInterfaceWrapper::IsNetworkConnecting", ret0},
{"UnityEngine.Switch.NetworkInterfaceWrapper::IsNetworkConnectingOnBackground", ret0},
{"UnityEngine.Switch.NetworkInterfaceWrapper::IsNetworkFinished", ret1},
{"UnityEngine.Switch.NetworkInterfaceWrapper::SetNetworkConnectedEnabled", nop},
{"UnityEngine.Switch.NetworkInterfaceWrapper::SetNetworkConnectingOnBackground", nop},
