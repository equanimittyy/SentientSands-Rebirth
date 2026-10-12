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

// Background threads hand results to the game thread only through this queue
void QueueMessage(const std::string &message);
// Posts on a new thread and queues "CMD: <command>: <tag>|<reply>". The tag
// comes back with the reply: a request number, which drops a reply that a
// newer request made stale, or the ID that a write named
void PostForGameThread(const std::wstring &endpoint, const std::string &json,
                       const std::string &command, const std::string &tag);
bool SplitTaggedReply(const std::string &data, std::string &tag,
                      std::string &reply);
// False for a reply that a newer request made stale
bool TakeTaggedReply(const std::string &data, int request, std::string &reply);
std::string FailureText(const std::string &prefixKey, const std::string &reply);
void NotifyText(const std::string &text);
