import ctypes
import logging
import os
import subprocess
import time

def kill_old_servers():
    try:
        result = subprocess.run(
            ['netstat', '-aon'], capture_output=True, text=True, shell=True
        )
        for line in result.stdout.splitlines():
            if ':5000' in line and 'LISTENING' in line:
                parts = line.strip().split()
                pid = int(parts[-1])
                if pid > 0 and pid != os.getpid():
                    logging.info(f"SYSTEM: Stopping the old server process (PID {pid}) on port 5000.")
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                                 capture_output=True, shell=True)
                    time.sleep(1)
    except Exception as e:
        logging.warning(f"SYSTEM: Cannot check port 5000 for an old server: {e}")

def monitor_kenshi_process():
    """The plugin launches the server, so the parent is Kenshi; exit when it does."""
    try:
        ppid = os.getppid()
        if ppid <= 1:
            logging.info("SYSTEM: Parent PID is 0 or 1, skipping auto-shutdown monitor.")
            return
            
        logging.info(f"SYSTEM: Monitoring parent process (PID {ppid}) for auto-shutdown.")
        
        PROCESS_QUERY_INFORMATION = 0x0400
        STILL_ACTIVE = 259
        
        kernel32 = ctypes.windll.kernel32
        
        while True:
            handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, ppid)
            if not handle:
                logging.info(f"SYSTEM: Parent Kenshi process (PID {ppid}) no longer found. Shutting down server.")
                os._exit(0)
                
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                if exit_code.value != STILL_ACTIVE:
                    kernel32.CloseHandle(handle)
                    logging.info(f"SYSTEM: Parent Kenshi process (PID {ppid}) has exited. Shutting down server.")
                    os._exit(0)
            else:
                kernel32.CloseHandle(handle)
                logging.warning(f"SYSTEM: Failed to query parent process state. Assuming it closed. Shutting down server.")
                os._exit(0)
            
            kernel32.CloseHandle(handle)
            time.sleep(5) 
            
    except Exception as e:
        logging.error(f"SYSTEM: Error in kenshi process monitor: {e}")
