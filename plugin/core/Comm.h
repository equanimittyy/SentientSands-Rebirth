#pragma once
#include <string>
#include <windows.h>

// Closes the handle, which leaves the thread running
void StartThread(LPTHREAD_START_ROUTINE start, LPVOID arg);
DWORD WINAPI PipeThread(LPVOID lpParam);
void AsyncPostToPython(const std::wstring &endpoint,
                       const std::string &jsonData);
void PostToPython(const std::wstring &endpoint, const std::string &jsonData);
std::string PostToPythonWithResponse(const std::wstring &endpoint,
                                     const std::string &jsonData);
DWORD WINAPI RadiantPollThread(LPVOID lpParam);
