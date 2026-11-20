"""Read-only OS process identity: PID plus creation time; zombies are not live."""
from pathlib import Path
import sys

def process_identity(pid):
 """PID + OS creation time avoids mistaking a reused PID for a live worker."""
 if sys.platform!='win32':
  try:
   fields=Path(f'/proc/{pid}/stat').read_text().split(') ')[1].split()
   return None if fields[0]=='Z' else fields[19]
  except (OSError,IndexError):return None
 import ctypes
 from ctypes import wintypes
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
 kernel.CloseHandle.argtypes=[wintypes.HANDLE]
 kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
 kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
 handle=kernel.OpenProcess(0x1000,False,pid)
 if not handle:return None
 try:
  code=wintypes.DWORD()
  if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value!=259:return None
  times=[wintypes.FILETIME() for _ in range(4)]
  if not kernel.GetProcessTimes(handle,*[ctypes.byref(t) for t in times]):return None
  return str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)
 finally:kernel.CloseHandle(handle)