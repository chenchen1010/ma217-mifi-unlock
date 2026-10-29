"""Bounded read-only observation following a separately authorized SIM selection."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import time

from mifi_probe import MiFi
from verify_mifi_internet import fetch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-ip', required=True)
    parser.add_argument('--interface-index', required=True, type=int)
    parser.add_argument('--seconds', type=int, default=75)
    parser.add_argument('--skip-internet-check', action='store_true',
                        help='Observe state only, without generating Internet test traffic.')
    args = parser.parse_args()
    if not 10 <= args.seconds <= 600:
        raise SystemExit('Observation must be bounded to 10–600 seconds.')
    client = MiFi(args.source_ip)
    client.login()
    started = time.monotonic()
    report = {'captured_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'source_ip': args.source_ip, 'interface_index': args.interface_index,
              'read_only_observation': True, 'internet_checks_enabled': not args.skip_internet_check,
              'samples': [], 'https_checks': []}
    path = Path(__file__).parent / 'artifacts' / ('sim-observation-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '.json')
    futures = []
    next_internet_check = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        while time.monotonic() - started < args.seconds:
            try:
                sim = client.read('mss_support_info')
                home = client.read('homepage_info')
                status = client.read('status_info')
                external = next(s for s in sim['sim_list'] if s['sim_name'] == 'USIM')
                sample = {'elapsed_seconds': round(time.monotonic() - started, 1),
                          'uptime_seconds': status.get('run_seconds'),
                          'current_sim_id': sim.get('current_sim_id'),
                          'sole_sim_id': sim.get('sole_sim_id'), 'switch_mode': sim.get('switch_mode'),
                          'current_sim_banned': sim.get('current_sim_banned'),
                          'external_banned': external.get('sim_banned'),
                          'active_iccid_matches_external': bool(external.get('sim_iccid')) and external['sim_iccid'] == home.get('iccid'),
                          'operator': home.get('network_name'), 'pc_valid': status.get('pc_valid'),
                          'tx_byte_all': status.get('tx_byte_all'), 'rx_byte_all': status.get('rx_byte_all')}
                if not args.skip_internet_check and sample['elapsed_seconds'] >= next_internet_check and sample['current_sim_id'] == '2' and sample['active_iccid_matches_external'] and sample['operator'] == 'CHN TELECOM':
                    for domain in ('www.baidu.com', 'www.qq.com'):
                        futures.append((domain, sample['elapsed_seconds'], pool.submit(fetch, domain, args.source_ip, args.interface_index)))
                    next_internet_check = sample['elapsed_seconds'] + 60
            except Exception as exc:
                sample = {'elapsed_seconds': round(time.monotonic() - started, 1), 'error': str(exc)}
            report['samples'].append(sample)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(sample, ensure_ascii=False), flush=True)
            time.sleep(3)
        for domain, scheduled_at, future in futures:
            try:
                check = future.result()
            except Exception as exc:
                check = {'domain': domain, 'success': False, 'error': str(exc)}
            check['scheduled_at_elapsed_seconds'] = scheduled_at
            report['https_checks'].append(check)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'https_checks': report['https_checks'], 'saved_local': str(path)}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
