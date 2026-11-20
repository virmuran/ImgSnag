"""history_manager 回归测试（纯逻辑，不碰 Qt、不碰用户真实 history.db）。

十二、v1.8.1 修复：重新解析不许抹掉下载记录（test_history.py）

  history_manager.add 原来是「先删后插」：已下载过的链接再解析一次，
  done 那行连同 save_path 被整个删掉，换成一条「已解析、0 下载」——
  用户看起来就是下载凭空消失了。修复后：
  a) 已有下载（done/partial 且有 save_path）→ 只刷新解析时间/图片数/备注，
     下载状态、张数、保存路径原样保留；
  b) 没有下载记录（scanned/failed）→ 照旧整体覆盖；
  c) 同一 URL 始终只有一行（返回的 id 不变），下载回调 update 那行还能找到。

  全部用临时目录的独立 db，绝不读写用户的 ~/.imgsnag/history.db。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_image_dl.history_manager import HistoryManager

_passed = 0
_failed = []


def check(cond, label):
    global _passed
    if cond:
        _passed += 1
    else:
        _failed.append(label)
        print(f'  ✗ {label}')


def eq(got, want, label):
    check(got == want, f'{label}\n      得到: {got}\n      期望: {want}')


def _temp_hm():
    return HistoryManager(db_path=os.path.join(
        tempfile.mkdtemp(prefix='imgsnag_hist_'), 'history.db'))


def _row(hm, url):
    rows = [r for r in hm.get_all() if r.source_url == url]
    return rows[0] if rows else None


URL = 'https://mp.weixin.qq.com/s/AbCdEf'


def test_reparse_preserves_done():
    print('\n[HIS-1] 已下载的记录，重新解析（scanned）不丢下载信息')
    hm = _temp_hm()
    folder = os.path.join(tempfile.gettempdir(), 'imgsnag_some_batch')
    hid = hm.add(URL, total_images=8, success_images=8, save_path=folder, status='done')

    # 重新解析同一链接：解析成功、还没下载
    hid2 = hm.add(URL, total_images=8, success_images=0, status='scanned')
    eq(hid2, hid, '同一 URL 复用同一行（id 不变，下载回调还能找到）')
    eq(hm.count(), 1, '还是只有一行，不会多出一条「已解析」')
    r = _row(hm, URL)
    eq(r.status, 'done', '状态仍是「已下载」——图还在磁盘上')
    eq(r.save_path, folder, '保存路径原样保留（「查看」按钮得还能用）')
    eq(r.success_images, 8, '已下载张数原样保留')


def test_reparse_preserves_partial():
    print('\n[HIS-2] 部分成功的记录同样受保护')
    hm = _temp_hm()
    folder = os.path.join(tempfile.gettempdir(), 'imgsnag_partial_batch')
    hm.add(URL, total_images=6, success_images=4, save_path=folder, status='partial')
    hm.add(URL, total_images=6, success_images=0, status='scanned')
    r = _row(hm, URL)
    eq(r.status, 'partial', '部分成功不被重新解析覆盖')
    eq(r.save_path, folder, '路径保留')
    eq(r.success_images, 4, '张数保留')


def test_reparse_failed_keeps_download():
    print('\n[HIS-3] 重新解析失败（文章被删是常态）更不能毁掉下载记录')
    hm = _temp_hm()
    folder = os.path.join(tempfile.gettempdir(), 'imgsnag_keep_batch')
    hm.add(URL, total_images=5, success_images=5, save_path=folder, status='done')
    hm.add(URL, total_images=0, success_images=0, status='failed', note='HTTP 404')
    r = _row(hm, URL)
    eq(r.status, 'done', '解析失败也不改「已下载」状态')
    eq(r.save_path, folder, '路径保留')
    eq(r.note, 'HTTP 404', '失败原因写进备注（时间线能看出来最近一次解析挂了）')


def test_no_download_still_overwrites():
    print('\n[HIS-4] 没有下载记录的照旧整体覆盖')
    hm = _temp_hm()
    hm.add(URL, total_images=5, success_images=0, status='scanned')
    hm.add(URL, total_images=0, success_images=0, status='failed', note='超时')
    r = _row(hm, URL)
    eq(r.status, 'failed', 'scanned → failed 正常覆盖')
    eq(hm.count(), 1, '仍是一行')

    hm.add(URL, total_images=7, success_images=0, status='scanned')
    r = _row(hm, URL)
    eq(r.status, 'scanned', 'failed → scanned 正常覆盖')
    eq(r.total_images, 7, '图片数刷新')


def test_download_update_after_reparse():
    print('\n[HIS-5] 重新解析后再下载，走 update 正常落账')
    hm = _temp_hm()
    folder = os.path.join(tempfile.gettempdir(), 'imgsnag_old_batch')
    hid = hm.add(URL, total_images=8, success_images=8, save_path=folder, status='done')
    hid2 = hm.add(URL, total_images=8, success_images=0, status='scanned')
    new_folder = os.path.join(tempfile.gettempdir(), 'imgsnag_new_batch')
    hm.update(hid2, success_images=8, save_path=new_folder, status='done')
    r = _row(hm, URL)
    eq(r.id, hid, '还是同一行')
    eq(r.save_path, new_folder, '保存路径指向新批次文件夹')
    eq(r.status, 'done', '状态 done')


def test_distinct_urls():
    print('\n[HIS-6] 不同 URL 互不干扰')
    hm = _temp_hm()
    hm.add(URL, total_images=8, success_images=8,
           save_path=tempfile.gettempdir(), status='done')
    other = 'https://mp.weixin.qq.com/s/Other'
    hid = hm.add(other, total_images=3, success_images=0, status='scanned')
    check(hid != _row(hm, URL).id, '不同 URL 各自一行')
    eq(hm.count(), 2, '共两行')
    eq(_row(hm, URL).status, 'done', '原记录不受影响')


def test_find_previous_hits():
    print('\n[HIS-7] find_previous：查「之前解析过」的记录')
    hm = _temp_hm()
    eq(hm.find_previous(URL), None, '空库里查 = 没解析过')
    folder = os.path.join(tempfile.gettempdir(), 'imgsnag_prev_batch')
    hm.add(URL, total_images=8, success_images=8, save_path=folder, status='done')
    prev = hm.find_previous(URL)
    check(prev is not None, '已有记录能查到')
    eq(prev.status, 'done', '查到的是那条下载记录')
    # 同一 URL 只保留一行 —— 先查后落库的顺序在界面层保证，这里验证查到的
    # 不是"自己刚落的"，落库前查到的必然是上一轮的旧记录
    eq(prev.source_url, URL, 'URL 对得上')
    # 失败的记录不算「解析过」：失败了用户多半正想再试
    hm2 = _temp_hm()
    hm2.add(URL, total_images=0, success_images=0, status='failed', note='404')
    eq(hm2.find_previous(URL), None, 'failed 记录不提醒')
    eq(hm2.find_previous(''), None, '空 URL 直接返回 None')


def test_find_previous_normalizes():
    print('\n[HIS-8] 参数顺序不同的同一篇文章也能对上（归一化比对）')
    hm = _temp_hm()
    hm.add('https://mp.weixin.qq.com/s?__biz=MzA1&mid=2247&idx=1&sn=abc',
           total_images=6, success_images=6,
           save_path=tempfile.gettempdir(), status='done')
    # 同一篇从另一个入口复制：参数顺序不同
    shuffled = hm.find_previous(
        'https://mp.weixin.qq.com/s?idx=1&mid=2247&sn=abc&__biz=MzA1')
    check(shuffled is not None, '参数排序后能命中')
    # 不同文章不能误判
    other = hm.find_previous(
        'https://mp.weixin.qq.com/s?__biz=MzA1&mid=2247&idx=1&sn=xyz')
    eq(other, None, 'sn 不同 = 另一篇文章，不误报')
    # 大小写域名 / 带锚点也归一
    noisy = hm.find_previous(
        'HTTPS://MP.WEIXIN.QQ.COM/s?__biz=MzA1&mid=2247&idx=1&sn=abc#imgIndex=2')
    check(noisy is not None, '域名大小写与锚点不碍事')
    # 归一化是纯比对用的，库里存的原文不动
    eq(hm.get_all()[0].source_url,
       'https://mp.weixin.qq.com/s?__biz=MzA1&mid=2247&idx=1&sn=abc',
       '库里的原始 URL 原样保留')


def test_previous_hint_text():
    print('\n[HIS-9] previous_hint：提醒文案（两端共用这一处）')
    hm = _temp_hm()
    folder = os.path.join(tempfile.gettempdir(), 'imgsnag_hint_batch')
    hm.add(URL, total_images=8, success_images=8, save_path=folder, status='done')
    tip = hm.find_previous(URL).previous_hint()
    check('已下载 8 张' in tip, f'下载过的说张数 —— {tip}')
    check('月' in tip and '日' in tip, f'时间用「几月几日」的人话 —— {tip}')

    hm.add('https://mp.weixin.qq.com/s/Scan2', total_images=5, status='scanned')
    tip2 = hm.find_previous('https://mp.weixin.qq.com/s/Scan2').previous_hint()
    check('只解析过、没下载' in tip2, f'没下载过的直说 —— {tip2}')

    hm.add('https://mp.weixin.qq.com/s/Part3', total_images=6, success_images=4,
           status='partial')
    tip3 = hm.find_previous('https://mp.weixin.qq.com/s/Part3').previous_hint()
    check('4/6' in tip3 and '部分成功' in tip3, f'部分成功的说比例 —— {tip3}')


def main():
    test_reparse_preserves_done()
    test_reparse_preserves_partial()
    test_reparse_failed_keeps_download()
    test_no_download_still_overwrites()
    test_download_update_after_reparse()
    test_distinct_urls()
    test_find_previous_hits()
    test_find_previous_normalizes()
    test_previous_hint_text()
    print(f'\n{"=" * 46}')
    print(f'通过 {_passed} 项，失败 {len(_failed)} 项')
    if _failed:
        for f in _failed:
            print(f'  ✗ {f}')
        sys.exit(1)
    print('全部通过')


if __name__ == '__main__':
    main()
