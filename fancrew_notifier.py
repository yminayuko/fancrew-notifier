#!/usr/bin/env python3
"""Fancrew Tokyo / solo visit availability watcher. No applications are submitted."""
import argparse
import html
import json
import logging
import os
from pathlib import Path
import random
import re
import secrets
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent
SEARCH_URL = ('https://www.fancrew.jp/search/result/1?areaId='
              '121%2C122%2C123%2C124%2C125%2C126%2C127%2C128%2C129%2C130%2C131%2C132%2C133%2C134%2C135%2C136%2C137%2C138%2C139%2C140%2C141%2C142%2C143%2C145%2C146%2C147%2C148%2C149&onlySoloVisitFlg=true')
CLOSED = re.compile(r'当選枠.{0,12}(?:埋ま|満)|募集.{0,8}(?:終了|停止)|応募.{0,8}(?:終了|停止)|満員|現在.{0,8}応募できません')
BLOCKED = re.compile(r'verify you are human|checking your browser|unusual traffic|アクセスが制限|ロボットではない|アクセスが拒否', re.I)

class StopMonitoring(Exception):
    pass

def key_for(url):
    p = urlparse(url)
    if p.scheme != 'https' or p.hostname != 'www.fancrew.jp':
        raise ValueError('ファンくる以外のURLは開けません')
    return p.path + ('?classicFlg=true' if 'classicFlg=true' in p.query else '?classicFlg=false')

def classify(text, controls):
    """Unknown is never interpreted as a closed slot."""
    text = text.split('こちらもおすすめ')[0]
    if CLOSED.search(text):
        return 'closed'
    for c in controls:
        if re.fullmatch(r'(?:モニターに応募する|このモニターに応募する|すぐに応募する|応募する)', c['text'].strip()):
            if c['visible'] and not c['disabled']:
                return 'open'
    return 'unknown'

def new_openings(old, observations, initialized, notify_existing=False):
    return [item for k, item in observations.items()
            if item['status'] == 'open' and old.get(k, {}).get('status') != 'open'
            and (initialized or notify_existing)]

def save_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)

def load_notification_config():
    topic = os.environ.get('NTFY_TOPIC')
    if topic:
        if not re.fullmatch(r'fancrew-[a-f0-9]{32}', topic):
            raise RuntimeError('NTFY_TOPICはfancrew-と32桁の小文字16進数で設定してください。')
        return {'topic':topic}
    path = ROOT/'notification.json'
    if not path.exists():
        raise RuntimeError('先に --setup-iphone を実行してください。')
    config = json.loads(path.read_text(encoding='utf-8'))
    if not re.fullmatch(r'fancrew-[a-f0-9]{32}', config.get('topic', '')):
        raise RuntimeError('notification.jsonのトピックが不正です。--setup-iphoneで設定してください。')
    return config

def setup_iphone():
    path = ROOT/'notification.json'
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'topic':'fancrew-'+secrets.token_hex(16)}, f)
    config = load_notification_config()
    print('iPhoneのntfyアプリで通知を許可し、次のトピックを購読してください。')
    print('サーバー: https://ntfy.sh')
    print('トピック: '+config['topic'])
    print('このトピック名は他人に共有しないでください。')
    print('購読後: python fancrew_notifier.py --test-notification')

def notify(title, message, click=SEARCH_URL):
    config = load_notification_config()
    key_for(click)
    payload = {'topic':config['topic'], 'title':title, 'message':message,
               'click':click, 'priority':3, 'tags':['fork_and_knife']}
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    if len(message.encode('utf-8')) > 3500:
        raise ValueError('通知本文が長すぎます。')
    request = Request('https://ntfy.sh/', data=body,
                      headers={'Content-Type':'application/json; charset=utf-8'}, method='POST')
    try:
        with urlopen(request, timeout=25) as response:
            result = json.loads(response.read())
            if result.get('event') != 'message' or not result.get('id'):
                raise RuntimeError('通知サービスから正常な応答を確認できませんでした。')
    except HTTPError as e:
        raise RuntimeError(f'通知送信失敗（HTTP {e.code}）。接続・サービス利用制限を確認してください。') from None
    except URLError:
        raise RuntimeError('通知サービスに接続できません。インターネット接続を確認してください。') from None

def notification_batches(items):
    batches, batch, size = [], [], 0
    for item in items:
        entry = item['title'][:180]+'\n'+item['url']+'\n条件: '+item['conditions'][:180]
        entry_size = len((entry+'\n\n').encode('utf-8'))
        if batch and size+entry_size > 2800:
            batches.append(batch)
            batch, size = [], 0
        batch.append((item, entry))
        size += entry_size
    if batch:
        batches.append(batch)
    return batches

def select_chunk(cards, cursor, limit):
    keys = sorted(cards)
    remaining = [k for k in keys if k > cursor] if limit else keys
    if not remaining:
        remaining = keys
    chosen = remaining[:limit] if limit else remaining
    return {k:cards[k] for k in chosen}, bool(chosen and chosen[-1] == keys[-1])

def check_block(page):
    text = page.locator('body').inner_text(timeout=15000)
    if BLOCKED.search(text):
        raise StopMonitoring('サイトのアクセス制限・人間確認を検出しました。監視を停止します。')
    return text

def navigate(page, url):
    key_for(url)
    response = page.goto(url, wait_until='domcontentloaded', timeout=60000)
    if response and response.status in (403, 429):
        raise StopMonitoring(f'HTTP {response.status} を受信しました。監視を停止します。')
    check_block(page)

CARD_JS = '''() => [...document.querySelectorAll('main h2')].map(h => {
    const li = h.closest('li'); const a = h.querySelector('a');
    if (!li || !a) return null;
    const fields = [...li.querySelectorAll('dt')].map(dt => ({label:dt.innerText,
        value:dt.nextElementSibling?.innerText || ''}));
    return {title:h.innerText, url:a.href, text:li.innerText, fields};
}).filter(Boolean)'''
CONTROL_JS = '''() => [...document.querySelectorAll('button,a,[role="button"]')].map(e => ({
    text:e.innerText.trim(), visible:!!(e.getClientRects().length),
    disabled:!!e.disabled || e.getAttribute('aria-disabled') === 'true'
}))'''

def collect_cards(page, max_pages):
    navigate(page, SEARCH_URL)
    page.wait_for_function("() => document.querySelector('main h2 a') || /0件/.test(document.querySelector('main')?.innerText || '')", timeout=60000)
    check_block(page)
    cards = {}
    fingerprints = set()
    for index in range(max_pages):
        page_cards = page.evaluate(CARD_JS)
        if not page_cards:
            if index == 0 and re.search(r'(?:/\s*0件|該当するモニター.{0,8}ありません|検索結果.{0,8}0件)', page.locator('main').inner_text()):
                return {}
            raise RuntimeError('検索結果を読み取れません。状態は変更しません。')
        fingerprint = tuple(c['url'] for c in page_cards)
        if fingerprint in fingerprints:
            raise RuntimeError('ページ送りの重複を検出しました。')
        fingerprints.add(fingerprint)
        for c in page_cards:
            # Do not silently accept nationwide results if the filter stops working.
            if '東京都' not in c['text'] or 'グルメ' not in c['text']:
                raise RuntimeError('東京都・グルメの検索条件が反映されていません。')
            key_for(c['url'])
            c['conditions'] = next((f['value'] for f in c['fields'] if '応募条件' in f['label']), '')
            cards[key_for(c['url'])] = c
        nxt = page.get_by_role('button', name='Go to next page', exact=True)
        if not nxt.count() or not nxt.is_enabled():
            return cards
        if index + 1 >= max_pages:
            raise RuntimeError('最大ページ数に達しました。--max-pagesを増やしてください。')
        previous = page_cards[0]['url']
        time.sleep(2)
        nxt.click()
        page.wait_for_function("u => document.querySelector('main h2 a')?.href !== u && !!document.querySelector('main h2 a')", arg=previous, timeout=60000)
        check_block(page)
    return cards

def inspect(page, card):
    navigate(page, card['url'])
    page.locator('h1').wait_for(timeout=60000)
    # Classic and modern details use different condition headings. h1 alone
    # appears before the application's conditions and availability controls.
    page.get_by_role('heading', name=re.compile(r'^(?:モニタールール|来店・応募条件)$')).wait_for(timeout=60000)
    page.wait_for_function("() => [...document.querySelectorAll('button,a,[role=button]')].some(e => /^(?:モニターに応募する|このモニターに応募する|すぐに応募する|応募する)$/.test(e.innerText.trim()) && e.getClientRects().length) || /募集終了|当選枠.{0,12}(?:埋ま|満)|このモニターに応募することはできません/.test(document.body.innerText)", timeout=30000)
    text = check_block(page)
    status = classify(text, page.evaluate(CONTROL_JS))
    return {k: card[k] for k in ('title', 'url', 'conditions')} | {'status':status, 'checked_at':time.strftime('%Y-%m-%d %H:%M:%S')}

def write_report(items):
    available = [i for i in items.values() if i['status'] == 'open']
    rows = ''.join('<li><a href="'+html.escape(i['url'], quote=True)+'">'+html.escape(i['title'])+'</a><p>'+html.escape(i['conditions'])+'</p><small>最終確認 '+html.escape(i['checked_at'])+'</small></li>' for i in available)
    (ROOT/'available.html').write_text('<!doctype html><meta charset="utf-8"><title>ファンくる監視結果</title><style>body{font:16px sans-serif;max-width:900px;margin:40px auto;padding:20px}li{margin:24px 0}small{color:#666}</style><h1>東京都・一人：応募ボタンを確認した案件</h1><p>年齢・性別・参加履歴などの資格と最新の空き状況はリンク先で確認してください。</p><ul>'+rows+'</ul>', encoding='utf-8')

def main():
    parser = argparse.ArgumentParser(description='ファンくる 東京都・一人の空き通知（iPhone）')
    parser.add_argument('--interval', type=int, default=30, help='巡回終了後の待機時間（分、最短15分）')
    parser.add_argument('--max-pages', type=int, default=100)
    parser.add_argument('--once', action='store_true', help='1巡回で終了')
    parser.add_argument('--max-details', type=int, default=0, help='1回で確認する詳細件数。0は全件。クラウド用')
    parser.add_argument('--notify-existing', action='store_true', help='初回の募集中案件も通知')
    parser.add_argument('--test-notification', action='store_true')
    parser.add_argument('--setup-iphone', action='store_true', help='iPhone用通知トピックを生成・表示')
    parser.add_argument('--headed', action='store_true', help='監視用ブラウザを表示')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', handlers=[logging.StreamHandler(), logging.FileHandler(ROOT/'monitor.log', encoding='utf-8')])
    if args.setup_iphone:
        setup_iphone()
        return
    if args.test_notification:
        notify('ファンくる通知テスト', '東京都・一人の通知設定ができました。通知をタップすると検索ページが開きます。')
        print('通知サービスが送信を受け付けました。iPhoneで到着を確認してください。')
        return
    load_notification_config()
    if args.interval < 15 or args.max_pages < 1 or args.max_details < 0:
        parser.error('--intervalは15以上、--max-pagesは1以上です。')
    import fcntl
    lock = (ROOT/'monitor.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('別の監視プログラムが実行中です。')
    state_path = ROOT/'state.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'initialized':False,'items':{}}
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(locale='ja-JP')
        search = context.new_page()
        detail = context.new_page()
        failures = 0
        try:
            while True:
                try:
                    cards = collect_cards(search, args.max_pages)
                    selected, reached_end = select_chunk(cards, state.get('cursor',''), args.max_details)
                    logging.info('東京都・一人：全%s案件中、今回%s案件を確認します', len(cards), len(selected))
                    observed = {}
                    errors = 0
                    for k, card in selected.items():
                        try:
                            item = inspect(detail, card)
                            if item['status'] == 'unknown':
                                logging.warning('判定不能: %s', card['title'])
                                continue
                            observed[k] = item
                        except StopMonitoring:
                            raise
                        except Exception as e:
                            errors += 1
                            logging.warning('取得失敗: %s %s (%s: %s)', card['title'], card['url'], type(e).__name__, str(e))
                            if errors >= 5:
                                raise RuntimeError('詳細ページが繰り返し失敗しました。')
                        time.sleep(2 + random.random())
                    if cards and not observed:
                        raise RuntimeError('全案件が判定不能です。サイト表示の確認が必要です。')
                    openings = new_openings(state['items'], observed, state['initialized'], args.notify_existing)
                    report_items = state['items'] | observed
                    write_report({k:v for k,v in report_items.items() if k in cards})
                    if openings:
                        batches = notification_batches(openings)
                        for number, batch in enumerate(batches, 1):
                            message = '\n\n'.join(entry for _, entry in batch)
                            notify(f'ファンくる：東京都・一人 {len(openings)}件 ({number}/{len(batches)})',
                                   message, click=batch[0][0]['url'])
                        for i in openings:
                            logging.info('新しく応募ボタンを確認: %s %s', i['title'], i['url'])
                    state['items'].update(observed)
                    # Missing items become unknown rather than closed. Unknown preserves
                    # the last confirmed status to avoid false reopen notifications.
                    if reached_end or not cards:
                        state['initialized'] = True
                    state['cursor'] = next(reversed(selected), '') if args.max_details else ''
                    save_json(state_path, state)
                    logging.info('巡回完了：判定済み%s件、新規通知%s件。初回は基準状態を保存します。',len(observed),len(openings))
                    failures = 0
                except StopMonitoring as e:
                    logging.error('%s',e)
                    try:
                        notify('ファンくる監視を停止',str(e))
                    except Exception:
                        logging.error('停止通知も送信できませんでした。')
                    return 2
                except Exception as e:
                    failures += 1
                    logging.error('巡回失敗（状態は保存しません）: %s',e)
                    if failures >= 3 or args.once:
                        try:
                            notify('ファンくる監視エラー','取得または通知に失敗しました。実行ログを確認してください。')
                        except Exception:
                            logging.error('エラー通知も送信できませんでした。')
                        return 1
                if args.once:
                    return 0
                time.sleep(args.interval*60)
        finally:
            browser.close()

if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print('\n監視を停止しました。')
