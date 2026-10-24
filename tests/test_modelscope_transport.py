import unittest
from unittest.mock import AsyncMock
from app.updates.download import Policy, sources

ENTRY = 'https://modelscope.cn/models/MaruYui/TachiTalk-Voice-Runtime/resolve/master/'
SOURCE = {'name':'魔搭', 'layout':'modelscope', 'prefix':ENTRY}
PART = 'https://github.com/maruyui-dev/TachiTalk/releases/download/v1.3.0/voice-v2ProPlus-cu128-runtime-1.zip.part000'

class ModelScopePolicyTests(unittest.TestCase):
    def test_independent_entry_mapping_preserves_original_signed_url(self):
        self.assertEqual(Policy().source_url(PART, SOURCE), ENTRY + PART.rsplit('/',1)[1])
        self.assertEqual(Policy().source_url('https://github.com/maruyui-dev/TachiTalk/releases/latest/download/voice-manifest.json', SOURCE), ENTRY+'voice-manifest.json')

    def test_only_uploaded_voice_release_is_mapped(self):
        for url in (PART.replace('v1.3.0','v9.0.0'), PART.replace('part000','main.exe')):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Policy().source_url(url, SOURCE)

    def test_modelscope_redirect_trust_is_host_and_path_limited(self):
        initial=ENTRY+'voice-manifest.json'
        Policy().redirect('https://cdn-lfs-cn-1.modelscope.cn/prod/lfs-objects/12/d8/'+'a'*60+'?temporary=1',initial)
        for url in ('https://evil.modelscope.cn/prod/lfs-objects/a', 'https://cdn-lfs-cn-1.modelscope.cn/other',
                    'http://cdn-lfs-cn-1.modelscope.cn/prod/lfs-objects/a','https://github.com/unrelated'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Policy().redirect(url,initial)

    def test_retired_cloudflare_cannot_be_reenabled_by_raw_config(self):
        config={'sources':[{'name':'Cloudflare','enabled':True,'prefix':'https://download.jieyiblog.me/','layout':'r2'}]}
        self.assertEqual(sources(config),[])


class ModelScopeTemporaryURLTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_lfs_response_re_resolves_entry_and_preserves_range(self):
        from app.updates.download import request
        class Response:
            def __init__(self,status,location=None):
                self.status=status
                self.headers={'Location':location} if location else {}
                self.closed=False
            def release(self):self.closed=True
            def close(self):self.closed=True
        first='https://cdn-lfs-cn-1.modelscope.cn/prod/lfs-objects/12/d8/'+'a'*60+'?expires=old'
        second=first.replace('old','new')
        replies=[Response(302,first),Response(403),Response(302,second),Response(206)]
        session=type('Session',(),{})()
        session.get=AsyncMock(side_effect=replies)
        headers={'Range':'bytes=512-','If-Range':'"strong-etag"'}
        response=await request(session,ENTRY+'voice-v2ProPlus-cu128-runtime-1.zip.part000',headers,Policy())
        self.assertEqual(response.status,206)
        calls=session.get.call_args_list
        self.assertEqual(calls[0].args[0],calls[2].args[0])
        self.assertEqual(calls[1].args[0],first)
        self.assertEqual(calls[3].args[0],second)
        self.assertTrue(replies[1].closed)
        for call in calls:
            self.assertEqual(call.kwargs['headers']['Range'],'bytes=512-')
            self.assertEqual(call.kwargs['headers']['If-Range'],'"strong-etag"')
            self.assertFalse(call.kwargs['allow_redirects'])
