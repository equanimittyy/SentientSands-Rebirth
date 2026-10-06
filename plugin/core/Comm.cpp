#include "Comm.h"
#include "Globals.h"
#include "Utils.h"
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
      if (!fullMsg.empty()) {
        EnterCriticalSection(&g_msgMutex);
        g_messageQueue.push_back(fullMsg);
        LeaveCriticalSection(&g_msgMutex);
      }
    }

    DisconnectNamedPipe(hPipe);
    CloseHandle(hPipe);
  }
  return 0;
}

void PostToPython(const std::wstring &endpoint, const std::string &jsonData) {
  HINTERNET hSession = NULL, hConnect = NULL, hRequest = NULL;
  BOOL bResults = FALSE;

  hSession =
      WinHttpOpen(L"SentientSands/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                  WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);

  if (hSession) {
    WinHttpSetTimeouts(hSession, 5000, 5000, 5000, 5000);
    hConnect = WinHttpConnect(hSession, L"localhost", 5000, 0);
  }

  if (hConnect)
    hRequest =
        WinHttpOpenRequest(hConnect, L"POST", endpoint.c_str(), NULL,
                           WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, 0);

  if (hRequest) {
    bResults = WinHttpSendRequest(
        hRequest, L"Content-Type: application/json\r\n", (DWORD)-1L,
        (LPVOID)jsonData.c_str(), (DWORD)jsonData.length(),
        (DWORD)jsonData.length(), 0);
  }

  if (bResults) {
    WinHttpReceiveResponse(hRequest, NULL);
  } else {
    std::string endp(endpoint.begin(), endpoint.end());
    Log(LOG_WARN, "HTTP: Failed to POST to " + endp +
                      " Error: " + ToString((int)GetLastError()));
  }

  if (hRequest)
    WinHttpCloseHandle(hRequest);
  if (hConnect)
    WinHttpCloseHandle(hConnect);
  if (hSession)
    WinHttpCloseHandle(hSession);
}

std::string PostToPythonWithResponse(const std::wstring &endpoint,
                                     const std::string &jsonData) {
  HINTERNET hSession = NULL, hConnect = NULL, hRequest = NULL;
  BOOL bResults = FALSE;
  std::string responseBody = "";

  hSession =
      WinHttpOpen(L"SentientSands/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                  WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);

  if (hSession) {
    WinHttpSetTimeouts(hSession, 60000, 60000, 60000, 60000);
    hConnect = WinHttpConnect(hSession, L"127.0.0.1", 5000, 0);
  }

  if (hConnect)
    hRequest =
        WinHttpOpenRequest(hConnect, L"POST", endpoint.c_str(), NULL,
                           WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, 0);

  if (hRequest) {
    bResults = WinHttpSendRequest(
        hRequest, L"Content-Type: application/json\r\n", (DWORD)-1L,
        (LPVOID)jsonData.c_str(), (DWORD)jsonData.length(),
        (DWORD)jsonData.length(), 0);
  }

  if (bResults) {
    bResults = WinHttpReceiveResponse(hRequest, NULL);
  }

  if (bResults) {
    DWORD dwSize = 0;
    do {
      if (!WinHttpQueryDataAvailable(hRequest, &dwSize))
        break;
      if (dwSize == 0)
        break;

      char *pszOutBuffer = new char[dwSize + 1];
      DWORD dwDownloaded = 0;
      if (WinHttpReadData(hRequest, (LPVOID)pszOutBuffer, dwSize,
                          &dwDownloaded)) {
        pszOutBuffer[dwDownloaded] = '\0';
        responseBody += pszOutBuffer;
      }
      delete[] pszOutBuffer;
    } while (dwSize > 0);
  }

  if (hRequest)
    WinHttpCloseHandle(hRequest);
  if (hConnect)
    WinHttpCloseHandle(hConnect);
  if (hSession)
    WinHttpCloseHandle(hSession);

  return responseBody;
}

struct HttpTask {
  std::wstring endpoint;
  std::string data;
};

DWORD WINAPI AsyncHttpThread(LPVOID lpParam) {
  HttpTask *task = (HttpTask *)lpParam;
  PostToPython(task->endpoint, task->data);
  delete task;
  return 0;
}

void AsyncPostToPython(const std::wstring &endpoint,
                       const std::string &jsonData) {
  HttpTask *task = new HttpTask();
  task->endpoint = endpoint;
  task->data = jsonData;
  CreateThread(NULL, 0, AsyncHttpThread, task, 0, NULL);
}

DWORD WINAPI RadiantPollThread(LPVOID lpParam) {
  std::string *pJson = (std::string *)lpParam;
  Log(LOG_DEBUG, "RADIANT: Sending request to server...");
  std::string response = PostToPythonWithResponse(L"/radiant", *pJson);
  delete pJson;

  if (response.empty()) {
    Log(LOG_WARN, "RADIANT: Empty response or timeout from server.");
    return 0;
  }

  // Restart the interval on reply so a slow server doesn't shorten the gap between conversations
  g_lastRadiantTick = GetTickCount();
  Log(LOG_INFO, "RADIANT: Server answered " + GetJsonValue(response, "status") + ".");
  return 0;
}
