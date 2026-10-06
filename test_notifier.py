import unittest
from fancrew_notifier import classify, new_openings, key_for

class AvailabilityTests(unittest.TestCase):
    def control(self, disabled=False):
        return [{'text':'モニターに応募する','visible':True,'disabled':disabled}]
    def test_open(self):
        self.assertEqual(classify('モニタールール',self.control()),'open')
    def test_closed_overrides_button(self):
        self.assertEqual(classify('当選枠がすでに埋まっているモニターです。',self.control()),'closed')
    def test_disabled_and_unknown_do_not_notify(self):
        self.assertEqual(classify('モニタールール',self.control(True)),'unknown')
        self.assertEqual(classify('ログインしてください',[]),'unknown')
    def test_hidden_button(self):
        self.assertEqual(classify('応募', [{'text':'応募する','visible':False,'disabled':False}]),'unknown')
    def test_initial_baseline(self):
        observations={'a':{'title':'A','status':'open'}}
        self.assertEqual(new_openings({},observations,False),[])
        self.assertEqual(len(new_openings({},observations,False,True)),1)
    def test_new_and_reopened(self):
        old={'a':{'status':'open'},'b':{'status':'closed'}}
        observations={'a':{'status':'open'},'b':{'status':'open'},'c':{'status':'open'},'d':{'status':'unknown'}}
        self.assertEqual(new_openings(old,observations,True),[observations['b'],observations['c']])
    def test_url_boundary(self):
        with self.assertRaises(ValueError): key_for('https://example.com/detail2/1')
        self.assertNotEqual(key_for('https://www.fancrew.jp/detail2/1?classicFlg=true'),key_for('https://www.fancrew.jp/detail2/1?classicFlg=false'))

    def test_detail_templates_and_cancel_waiting(self):
        from unittest.mock import MagicMock, patch
        import fancrew_notifier as app
        card={'title':'魁力屋 東久留米店', 'url':'https://www.fancrew.jp/detail2/1?classicFlg=false', 'conditions':'1名'}
        for heading, text, disabled, expected in (
            ('モニタールール', 'モニタールール', False, 'open'),
            ('来店・応募条件', '来店・応募条件', False, 'open'),
            ('来店・応募条件', '現在当選枠が満員・応募条件などのため、応募ができません。', True, 'closed'),
            ('来店・応募条件', 'キャンセル待ちでのご応募が可能です。現在当選枠が満員となっています。', False, 'closed'),
        ):
            with self.subTest(heading=heading, expected=expected):
                page=MagicMock()
                def find_heading(role, name, **kwargs):
                    self.assertEqual(role, 'heading')
                    if not (name == heading or hasattr(name,'fullmatch') and name.fullmatch(heading)):
                        raise TimeoutError('The requested heading does not exist in this template')
                    return MagicMock()
                page.get_by_role.side_effect=find_heading
                page.evaluate.return_value=self.control(disabled)
                with patch.object(app,'navigate'), patch.object(app,'check_block',return_value=text):
                    self.assertEqual(app.inspect(page,card)['status'],expected)


class IphoneNotificationTests(unittest.TestCase):
    def test_japanese_payload_and_link(self):
        import json
        from unittest.mock import patch, MagicMock
        import fancrew_notifier as app
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"event":"message","id":"test"}'
        url='https://www.fancrew.jp/detail2/123?categoryId=1&classicFlg=true'
        with patch.object(app,'load_notification_config',return_value={'topic':'fancrew-'+'a'*32}), patch.object(app,'urlopen',return_value=response) as sender:
            app.notify('東京都・一人','テスト店舗',url)
            request=sender.call_args.args[0]
            payload=json.loads(request.data)
            self.assertEqual(request.full_url,'https://ntfy.sh/')
            self.assertEqual(payload['message'],'テスト店舗')
            self.assertEqual(payload['click'],url)
            self.assertEqual(payload['topic'],'fancrew-'+'a'*32)
    def test_split_all_items_within_byte_budget(self):
        import fancrew_notifier as app
        items=[{'title':'店'*180,'url':'https://www.fancrew.jp/detail2/'+str(i),'conditions':'条件'*180} for i in range(20)]
        batches=app.notification_batches(items)
        self.assertEqual([item for batch in batches for item,_ in batch],items)
        self.assertGreater(len(batches),1)
        for batch in batches:
            self.assertLessEqual(len('\n\n'.join(entry for _,entry in batch).encode('utf-8')),3500)
    def test_failure_is_not_success(self):
        from unittest.mock import patch
        from urllib.error import URLError
        import fancrew_notifier as app
        with patch.object(app,'load_notification_config',return_value={'topic':'fancrew-'+'b'*32}), patch.object(app,'urlopen',side_effect=URLError('network')):
            with self.assertRaisesRegex(RuntimeError,'接続できません'):
                app.notify('test','test')
    def test_setup_retains_existing_topic(self):
        import tempfile, json
        from pathlib import Path
        from unittest.mock import patch
        import fancrew_notifier as app
        with tempfile.TemporaryDirectory() as directory, patch.object(app,'ROOT',Path(directory)), patch('builtins.print'):
            app.setup_iphone()
            initial=json.loads((Path(directory)/'notification.json').read_text())
            self.assertRegex(initial['topic'],r'^fancrew-[a-f0-9]{32}$')
            app.setup_iphone()
            self.assertEqual(json.loads((Path(directory)/'notification.json').read_text()),initial)



class CloudTests(unittest.TestCase):
    def test_chunks_resume_and_wrap(self):
        from fancrew_notifier import select_chunk
        cards={str(i):{} for i in range(5)}
        first,end=select_chunk(cards,'',2)
        self.assertEqual(list(first),['0','1']); self.assertFalse(end)
        second,end=select_chunk(cards,'1',2)
        self.assertEqual(list(second),['2','3']); self.assertFalse(end)
        third,end=select_chunk(cards,'3',2)
        self.assertEqual(list(third),['4']); self.assertTrue(end)
        wrapped,end=select_chunk(cards,'4',2)
        self.assertEqual(list(wrapped),['0','1'])
        all_cards,end=select_chunk(cards,'3',0)
        self.assertEqual(len(all_cards),5); self.assertTrue(end)
    def test_cloud_topic_from_secret(self):
        import os
        from unittest.mock import patch
        from fancrew_notifier import load_notification_config
        with patch.dict(os.environ,{'NTFY_TOPIC':'fancrew-'+'a'*32}):
            self.assertEqual(load_notification_config()['topic'],'fancrew-'+'a'*32)
    def test_artifact_restore_uses_only_expected_files(self):
        import tempfile,io,json,zipfile
        from pathlib import Path
        from cloud_state import restore_zip
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:
            z.writestr('state.json',json.dumps({'initialized':True,'items':{},'cursor':'4'}))
            z.writestr('STOPPED','blocked')
            z.writestr('../unwanted','bad')
        with tempfile.TemporaryDirectory() as d:
            restore_zip(data.getvalue(),Path(d))
            self.assertEqual(json.loads((Path(d)/'state.json').read_text())['cursor'],'4')
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()),['STOPPED','state.json'])

if __name__=='__main__': unittest.main()
