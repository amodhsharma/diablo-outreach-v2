# Button 4, step 1: the last run

Written 2026-10-31 01:53 UTC

```
263 leads in the Diablo campaigns in Instantly
Instantly blocklist: 0 entries read (addresses and domains)
Deputy Managing Director sent only an automatic answer (the subject says "Abwesenheit"); it does not count as a reply, so the loop carries on
Senior Product Owner sent only an automatic answer (the subject says "Out of office"); it does not count as a reply, so the loop carries on
Leiterin Personal Schweiz sent only an automatic answer (the subject says "Automatische Antwort"); it does not count as a reply, so the loop carries on
CEO sent only an automatic answer (the text says "Automatisch generiert"); Instantly labelled it, the label is ignored; it does not count as a reply, so the loop carries on
Wrote 10 notes on contacts' timelines (email sent, bounced or replied)
LowPrice Sagl: no reply to the introduction; the company is now "Contacted, but no response, unqualified"
SansGluGlu (Le P'tit Mag): no reply to the introduction; the company is now "Contacted, but no response, unqualified"
Veganer-Shop.ch: no reply to the introduction; the company is now "Contacted, but no response, unqualified"
Alna Dietetique & Bio: no reply to the introduction; the company is now "Contacted, but no response, unqualified"
Running Concept (Michel Renck Sports): no reply to the introduction; the company is now "Contacted, but no response, unqualified"
KDC Nutrition: no reply to the introduction; the company is now "Contacted, but no response, unqualified"
La Bonbonnerie: no reply to the introduction; the company is now "Contacted, but no response, unqualified"
Sparposten.ch: no reply to the introduction; the company is now "Contacted, but no response, unqualified"
Planet Endurance: no reply to the introduction; the company is now "Contacted, but no response, unqualified"
UNEXPECTED ERROR: ionpool.py", line 793, in urlopen
    response = self._make_request(
               ^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/urllib3/connectionpool.py", line 542, in _make_request
    self._raise_timeout(err=e, url=url, timeout_value=read_timeout)
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/urllib3/connectionpool.py", line 373, in _raise_timeout
    raise ReadTimeoutError(
urllib3.exceptions.ReadTimeoutError: HTTPSConnectionPool(host='api.hubapi.com', port=443): Read timed out. (read timeout=30)

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/sync.py", line 1093, in main
    run(args.target, settings, HubSpot(), Instantly(), emails_api=Instantly(api_key=key) if key else None,
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/sync.py", line 549, in run
    moved = advance(hs, instantly, settings, log, emails_api=emails_api, statuses=statuses, leads=leads,
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/sync.py", line 1039, in advance
    hs.update_tagged("contacts", contact_updates)
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/hubspot_client.py", line 92, in update_tagged
    self._check_tags(object_type, [i for i, _ in updates], "change")
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/hubspot_client.py", line 66, in _check_tags
    found = {str(r["id"]): r.get("properties") for r in self.batch_read(object_type, ids, [TAG_PROPERTY])}
                                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/hubspot_client.py", line 221, in batch_read
    data = self.request(
           ^^^^^^^^^^^^^
  File "/home/runner/work/diablo-outreach-v2/diablo-outreach-v2/outreach/hubspot_client.py", line 142, in request
    resp = self.session.request(method, API + path, timeout=30, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/requests/sessions.py", line 651, in request
    resp = self.send(prep, **send_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/requests/sessions.py", line 784, in send
    r = adapter.send(request, **kwargs)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.12.15/x64/lib/python3.12/site-packages/requests/adapters.py", line 742, in send
    raise ReadTimeout(e, request=request)
requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='api.hubapi.com', port=443): Read timed out. (read timeout=30)

```
