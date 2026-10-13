#include "Comm.h"
#include "Globals.h"
#include "Utils.h"
#include <cstdlib>
#include <winhttp.h>

DWORD WINAPI PipeThread(LPVOID lpParam) {
  Log(LOG_INFO, "PIPE: Server thread started.");
  while (true) {
    HANDLE hPipe =
        CreateNamedPipeA("\\\\.\\pipe\\SentientSands", PIPE_ACCESS_DUPLEX,
                         PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                         PIPE_UNLIMITED_INSTANCES, 1048576, 1048576, 0, NULL);

    if (hPipe == INVALID_HANDLE_VALUE) {
      DWORD err = GetLastError();
      Log(LOG_ERROR,
          "PIPE: Failed to create pipe. Error: " + ToString((int)err));
      Sleep(2000);
      continue;
    }

    if (ConnectNamedPipe(hPipe, NULL) ||
        GetLastError() == ERROR_PIPE_CONNECTED) {
      char buffer[65536];
      DWORD bytesRead;
      std::string fullMsg = "";
      while (ReadFile(hPipe, buffer, sizeof(buffer) - 1, &bytesRead, NULL) &&
             bytesRead > 0) {
        buffer[bytesRead] = '\0';
        fullMsg += buffer;
      }
      if (!fullMsg.empty())
        QueueMessage(fullMsg);
    }

    DisconnectNamedPipe(hPipe);
    CloseHandle(hPipe);
  }
  return 0;
}

// 127.0.0.1, because the server binds only that address
static std::string Post(const std::wstring &endpoint, const std::string &json,
                        int timeoutMs) {
  std::string body;
  HINTERNET session =
      WinHttpOpen(L"SentientSands/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                  WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
  HINTERNET connect = NULL, request = NULL;
  if (session) {
    WinHttpSetTimeouts(session, timeoutMs, timeoutMs, timeoutMs, timeoutMs);
    connect = WinHttpConnect(session, L"127.0.0.1", 5000, 0);
  }
  if (connect)
    request = WinHttpOpenRequest(connect, L"POST", endpoint.c_str(), NULL,
                                 WINHTTP_NO_REFERER,
                                 WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
  bool answered =
      request &&
      WinHttpSendRequest(request, L"Content-Type: application/json\r\n",
                         (DWORD)-1L, (LPVOID)json.c_str(), (DWORD)json.length(),
                         (DWORD)json.length(), 0) &&
      WinHttpReceiveResponse(request, NULL);
  if (!answered) {
    Log(LOG_WARN, "HTTP: Failed to POST to " +
                      std::string(endpoint.begin(), endpoint.end()) +
                      " Error: " + ToString((int)GetLastError()));
  } else {
    char buffer[4096];
    DWORD available = 0;
    while (WinHttpQueryDataAvailable(request, &available) && available > 0) {
      DWORD read = 0;
      if (!WinHttpReadData(request, buffer,
                           available < sizeof(buffer) ? available
                                                      : (DWORD)sizeof(buffer),
                           &read) ||
          read == 0)
        break;
      body.append(buffer, read);
    }
  }
  if (request)
    WinHttpCloseHandle(request);
  if (connect)
    WinHttpCloseHandle(connect);
  if (session)
    WinHttpCloseHandle(session);
  return body;
}

std::string PostToPythonWithResponse(const std::wstring &endpoint,
                                     const std::string &jsonData) {
  return Post(endpoint, jsonData, 60000);
}

void StartThread(LPTHREAD_START_ROUTINE start, LPVOID arg) {
  HANDLE thread = CreateThread(NULL, 0, start, arg, 0, NULL);
  if (thread)
    CloseHandle(thread);
}

void QueueMessage(const std::string &message) {
  EnterCriticalSection(&g_msgMutex);
  g_messageQueue.push_back(message);
  LeaveCriticalSection(&g_msgMutex);
}

struct TaggedPost {
  std::wstring endpoint;
  std::string json;
  std::string command;
  std::string tag;
};

static DWORD WINAPI TaggedPostThread(LPVOID lpParam) {
  TaggedPost *t = (TaggedPost *)lpParam;
  std::string response = PostToPythonWithResponse(t->endpoint, t->json);
  QueueMessage("CMD: " + t->command + ": " + t->tag + "|" + response);
  delete t;
  return 0;
}

void PostForGameThread(const std::wstring &endpoint, const std::string &json,
                       const std::string &command, const std::string &tag) {
  TaggedPost *t = new TaggedPost();
  t->endpoint = endpoint;
  t->json = json;
  t->command = command;
  t->tag = tag;
  StartThread(TaggedPostThread, t);
}

bool SplitTaggedReply(const std::string &data, std::string &tag,
                      std::string &reply) {
  size_t start = data.find_first_not_of(' ');
  size_t sep = data.find('|');
  if (start == std::string::npos || sep == std::string::npos)
    return false;
  tag = data.substr(start, sep - start);
  reply = data.substr(sep + 1);
  return true;
}

bool TakeTaggedReply(const std::string &data, int request, std::string &reply) {
  std::string tag;
  return SplitTaggedReply(data, tag, reply) && atoi(tag.c_str()) == request;
}

std::string FailureText(const std::string &prefixKey,
                        const std::string &reply) {
  std::string error = GetJsonValue(reply, "message");
  if (error.empty())
    error = GetJsonValue(reply, "error");
  return T(prefixKey) + (error.empty() ? T("Unknown error") : error);
}

void NotifyText(const std::string &text) { QueueMessage("NOTIFY: " + text); }

struct HttpTask {
  std::wstring endpoint;
  std::string data;
};

DWORD WINAPI AsyncHttpThread(LPVOID lpParam) {
  HttpTask *task = (HttpTask *)lpParam;
  Post(task->endpoint, task->data, 5000);
  delete task;
  return 0;
}

void AsyncPostToPython(const std::wstring &endpoint,
                       const std::string &jsonData) {
  HttpTask *task = new HttpTask();
  task->endpoint = endpoint;
  task->data = jsonData;
  StartThread(AsyncHttpThread, task);
}
