"""Bounded, interface-bound HTTPS transfer for comparing device rate control.

Reads at most 16 MiB from Tencent's public download CDN into memory and discards
it. Does not save or execute software. This is a single-path comparison, not a
measurement of the carrier's maximum speed.
"""
import argparse, datetime as dt, http.client, json, ssl, time
from pathlib import Path
from urllib.parse import urlparse
from mifi_probe import MiFi
from verify_mifi_internet import bound_socket, resolve_a

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-ip',required=True)
    p.add_argument('--interface-index',type=int,required=True)
    p.add_argument('--label',choices=('before','after','after-reboot'),required=True)
    args=p.parse_args()
    c=MiFi(args.source_ip);c.login();sim=c.read('mss_support_info');home=c.read('homepage_info')
    ext=next(s for s in sim['sim_list'] if s['sim_id']=='2')
    assert sim['current_sim_id']=='2' and ext['sim_iccid']==home['iccid'] and home['network_name']=='CHN TELECOM'
    host='dldir1.qq.com';path='/weixin/Windows/WeChatSetup.exe';limit=16*1024*1024
    report={'started_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'label':args.label,
            'source_ip':args.source_ip,'interface_index':args.interface_index,'url':'https://'+host+path,
            'byte_limit':limit,'active_external_telecom_verified':True,'bytes_read':0,
            'limitation':'One bounded download path; not a carrier peak-speed test or controlled RF laboratory comparison.'}
    try:
        for attempt in range(3):
            addresses=resolve_a(host,args.source_ip,args.interface_index)
            with bound_socket(args.source_ip,args.interface_index) as raw:
                raw.connect((addresses[0],443))
                with ssl.create_default_context().wrap_socket(raw,server_hostname=host) as tls:
                    tls.sendall((f'GET {path} HTTP/1.1\r\nHost: {host}\r\nRange: bytes=0-{limit-1}\r\nUser-Agent: MiFi-Bounded-Rate-Check/1.0\r\nConnection: close\r\n\r\n').encode('ascii'))
                    response=http.client.HTTPResponse(tls);response.begin()
                    if response.status in (301,302,307,308):
                        redirected=urlparse(response.getheader('Location',''))
                        assert redirected.scheme=='https' and redirected.hostname and (redirected.hostname.endswith('.qq.com') or redirected.hostname.endswith('.cdntips.net'))
                        report.setdefault('redirect_hosts',[]).append(redirected.hostname)
                        host=redirected.hostname
                        path=redirected.path+('?' + redirected.query if redirected.query else '')
                        continue
                    report.update(http_status=response.status,content_range=response.getheader('Content-Range'),
                                  content_length=response.getheader('Content-Length'),certificate_validated=True,
                                  local_ipv4=tls.getsockname()[0],peer_ipv4=tls.getpeername()[0])
                    assert response.status in (200,206), f'Unexpected HTTP status {response.status}'
                    start=time.monotonic()
                    while report['bytes_read']<limit:
                        if time.monotonic()-start>45:raise TimeoutError('Bounded transfer exceeded 45 seconds')
                        data=response.read(min(65536,limit-report['bytes_read']))
                        if not data:break
                        report['bytes_read']+=len(data)
                    elapsed=time.monotonic()-start
                    report.update(transfer_seconds=elapsed,average_Mbps=report['bytes_read']*8/elapsed/1e6,
                                  completed=report['bytes_read']==limit)
                    break
        else:raise RuntimeError('Too many CDN redirects')
    except Exception as e:
        report.update(error=str(e),completed=False)
    dest=Path('artifacts')/('rate-'+args.label+'-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False),flush=True);print(dest)
    if not report['completed']:raise SystemExit(1)

if __name__=='__main__':main()
