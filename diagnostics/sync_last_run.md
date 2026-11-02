# Button 4, step 1: the last run

Written 2026-11-02 19:30 UTC

```
UNEXPECTED ERROR: stedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/urllib3/connectionpool.py", line 540, in _make_request
    response = conn.getresponse()
               ^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/urllib3/connection.py", line 638, in getresponse
    httplib_response = super().getresponse()
                       ^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/http/client.py", line 1478, in getresponse
    response.begin()
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/http/client.py", line 343, in begin
    version, status, reason = self._read_status()
                              ^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/http/client.py", line 312, in _read_status
    raise RemoteDisconnected("Remote end closed connection without"
urllib3.exceptions.ProtocolError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/sync.py", line 1232, in main
    run(args.target, settings, HubSpot(), Instantly(), emails_api=Instantly(api_key=key) if key else None,
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/sync.py", line 480, in run
    leads = instantly_view(instantly, settings["sync"]["campaign_prefix"])
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/next_in_line.py", line 74, in instantly_view
    for lead in instantly.list_leads(c["id"]):
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/instantly_client.py", line 198, in list_leads
    data = self.request("POST", "/leads/list", json=body)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/instantly_client.py", line 33, in request
    resp = self.session.request(method, API + path, timeout=60, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/requests/sessions.py", line 651, in request
    resp = self.send(prep, **send_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/requests/sessions.py", line 784, in send
    r = adapter.send(request, **kwargs)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/requests/adapters.py", line 711, in send
    raise ConnectionError(err, request=request)
requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))

```
