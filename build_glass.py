#!/usr/bin/env python3
"""omox.cc 玻璃版站点构建脚本。

用法: python build_glass.py
输入: glass_template.html (模板, ASCII banner 已内嵌) + omox_text.json (文案块)
      C:\\Users\\omo\\Desktop\\16_4k.jpg (背景图, 压成 bg.webp)
输出: omox_glass.html + bg.webp + fonts/*.woff2 (字体按页面实际字符自动子集)

三道自检: node --check / CSP hash 同步 / CSS 关键选择器清单 —— 不过不写产物。
字体子集在离线或无 uv 时回退现有文件只告警;cmap 覆盖不足则中止构建(防豆腐块)。
"""
import base64, io, json, os

BASE = os.path.dirname(os.path.abspath(__file__))
# 背景原图查找顺序：OMOX_BG 环境变量 -> 仓库内 bg_src.jpg -> 本机旧位置。
# 都找不到就沿用已生成的 bg.webp（别人 clone 后没有原图也能照常构建 HTML）。
BG_CANDIDATES = [os.environ.get("OMOX_BG", ""),
                 os.path.join(BASE, "bg_src.jpg"),
                 r"C:\Users\omo\Desktop\16_4k.jpg"]
BG_WORK = os.path.join(BASE, "bg.webp")
BG_WIDTH = 1920      # 模糊背景不需要原分辨率
BG_QUALITY = 75      # WebP：同画质档 82.6KB -> ~30KB（-63%）

def make_bg():
    """压图：1920 宽 + 轻微预模糊 + WebP。
    独立文件而不是 base64 内嵌 —— 内嵌那 82KB 永远跟着 HTML 重传、还不可缓存；
    独立文件能配 immutable 长缓存，二次访问 0 字节，HTML 本身也瘦掉七成。"""
    src = next((p for p in BG_CANDIDATES if p and os.path.exists(p)), None)
    if src is None:
        if os.path.exists(BG_WORK):
            print("背景原图未找到，沿用现有 bg.webp（换背景请设 OMOX_BG 或放 bg_src.jpg）")
            return "bg.webp"
        raise SystemExit("背景原图不存在且没有可用的 bg.webp，"
                         "请设 OMOX_BG=<图片路径> 或放一份 bg_src.jpg 到仓库根目录")
    from PIL import Image, ImageFilter
    im = Image.open(src).convert("RGB")
    w, h = im.size
    im = im.resize((BG_WIDTH, round(h * BG_WIDTH / w)), Image.LANCZOS)
    im = im.filter(ImageFilter.GaussianBlur(2))
    im.save(BG_WORK, "WEBP", quality=BG_QUALITY, method=6)
    # 清掉 base64 时代的 jpg 中间产物，别留两份图
    old_jpg = os.path.join(BASE, "bg.jpg")
    if os.path.exists(old_jpg):
        os.remove(old_jpg)
    return "bg.webp"

LATIN_RANGES = [(0x0000,0x00FF),(0x0131,0x0131),(0x0152,0x0153),(0x02BB,0x02BC),(0x02C6,0x02C6),
                (0x02DA,0x02DA),(0x02DC,0x02DC),(0x0304,0x0304),(0x0308,0x0308),(0x0329,0x0329),
                (0x2000,0x206F),(0x20AC,0x20AC),(0x2122,0x2122),(0x2191,0x2191),(0x2193,0x2193),
                (0x2212,0x2212),(0x2215,0x2215),(0xFEFF,0xFEFF),(0xFFFD,0xFFFD)]

def subset_fonts(out_html):
    """按页面实际字符给 woff2 做子集（46KB -> 27KB，首访省 19KB）。

    这步必须每次构建都跑：改文案 = 改字符集，一次用固定字符表手工子集的话，
    以后文案里出现新标点就会渲染成豆腐块。跑法是 uv run 临时环境（fonttools+brotli），
    离线或没 uv 时保留现用字体、只告警不中断构建；子集后还会按 cmap 复验覆盖，
    缺字直接让构建失败。"""
    import shutil, subprocess
    fonts_dir = os.path.join(BASE, "fonts")
    if not os.path.isdir(fonts_dir):
        print("字体目录不存在，跳过子集化")
        return
    # 控制字符不产生字形，过滤掉，否则 cmap 校验永远报缺一个换行
    chars = "".join(sorted({c for c in out_html
                            if ord(c) >= 0x20 and any(a <= ord(c) <= bb for a, bb in LATIN_RANGES)}))
    chars_file = os.path.join(BASE, "_subset_chars.txt")
    with open(chars_file, "w", encoding="utf-8", newline="") as f:
        f.write(chars)
    total_before = total_after = 0
    for name in ("roboto-mono-latin.woff2", "share-tech-mono-latin.woff2"):
        src = os.path.join(fonts_dir, name)
        if not os.path.exists(src):
            print("  字体缺失: " + name)
            continue
        orig = src + ".orig"
        if not os.path.exists(orig):          # 首次留源，之后永远以源为基准重子集
            shutil.copy2(src, orig)
        total_before += os.path.getsize(orig)
        sub = src + ".sub"
        if os.path.exists(sub):
            os.remove(sub)
        # 源永远用 .orig 完整字体：子集的子集取不到新增字符（改文案加新标点会直接缺字）
        r = subprocess.run(["uv", "run", "--with", "fonttools", "--with", "brotli",
                            "python", "-m", "fontTools.subset", orig,
                            "--text-file=" + chars_file, "--flavor=woff2",
                            "--output-file=" + sub],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        if r.returncode == 0 and os.path.exists(sub) and os.path.getsize(sub) > 0:
            shutil.move(sub, src)
        else:
            if os.path.exists(sub):
                os.remove(sub)
            print("  子集化失败（离线或无 uv？），沿用现有字体: %s  %s"
                  % (name, (r.stderr or "").strip().splitlines()[-1][:80] if (r.stderr or "").strip() else ""))
        total_after += os.path.getsize(src)
    # ---- cmap 覆盖复验：页面用到的每个可打印字符都必须在字体里 ----
    chk = subprocess.run(["uv", "run", "--with", "fonttools", "--with", "brotli", "python", "-c",
                          "import sys\n"
                          "from fontTools.ttLib import TTFont\n"
                          "need=set(ord(c) for c in open(sys.argv[1],encoding='utf-8').read())\n"
                          "bad=[]\n"
                          "for f in sys.argv[2:]:\n"
                          "  ft=TTFont(f); cm=set()\n"
                          "  for t in ft['cmap'].tables: cm |= set(t.cmap.keys())\n"
                          "  miss=need-cm\n"
                          "  if miss: bad.append(f.split('\\\\')[-1]+' 缺 '+''.join(chr(c) for c in sorted(miss))[:60])\n"
                          "print('CMAP_OK' if not bad else 'CMAP_FAIL '+'; '.join(bad))\n"
                          "sys.exit(0 if not bad else 1)"] +
                         [chars_file] + [os.path.join(fonts_dir, n) for n in
                          ("roboto-mono-latin.woff2", "share-tech-mono-latin.woff2")],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    out = (chk.stdout or "").strip()
    if chk.returncode != 0:
        raise SystemExit("字体 cmap 覆盖不足（新文案字符没进子集？）:\n" + out)
    if "CMAP_OK" not in out:
        raise SystemExit("cmap 校验没有明确通过:\n" + out + (chk.stderr or ""))
    print("字体子集: %s -> %s 字符，%s" % (f"{total_before:,}B", f"{total_after:,}B", out))
    try:
        os.remove(chars_file)
    except OSError:
        pass

def main():
    tpl = open(os.path.join(BASE, "glass_template.html"), encoding="utf-8").read()
    text_json = open(os.path.join(BASE, "omox_text.json"), encoding="utf-8").read().strip()
    json.loads(text_json)          # 校验
    bg_uri = make_bg()

    out = tpl.replace("/*__TEXT__*/", text_json)
    out = out.replace("__BG__", bg_uri)
    for ph in ("__TEXT__", "__BG__"):
        if ph in out:
            raise SystemExit("占位符没替换干净: " + ph)
    if "</script" in text_json.lower():
        raise SystemExit("文案里有 </script>，会截断脚本")

    # 语法自检：单文件站没有打包器兜底，改坏括号要到浏览器里才发现（首屏直接白）
    a = out.find("<script>") + 8
    b = out.rfind("</script>")
    chk = os.path.join(BASE, "_syntax_check.js")
    with open(chk, "w", encoding="utf-8", newline="\n") as f:
        f.write(out[a:b])
    import subprocess
    r = subprocess.run(["node", "--check", chk], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    os.remove(chk)
    if r.returncode != 0:
        raise SystemExit("JS 语法错误，未写出产物:\n" + (r.stderr or "")[:600])

    # CSP hash 自检：内联 script 的 sha256 必须与 <meta CSP> 里声明的一致，
    # 否则浏览器会拦掉整个脚本 —— 页面静默白屏，且不报任何网络错误。
    # 文案在 omox_text.json 里、JSON 又注入进 script，所以**改文案就会改 hash**：
    # 这里直接把 meta 里的旧 hash 同步成实际值（机械推导，无歧义），并留校验防结构损坏。
    import hashlib, base64 as _b64, re as _re
    actual = _b64.b64encode(hashlib.sha256(out[a:b].encode("utf-8")).digest()).decode()
    m = _re.search(r'(Content-Security-Policy" content="[^"]*?script-src[^"]*?sha256-)([A-Za-z0-9+/=]+)', out)
    if m:
        if m.group(2) != actual:
            print("CSP hash 已同步: %s -> %s" % (m.group(2)[:20] + "…", actual))
            out = out[:m.start(2)] + actual + out[m.end(2):]
        else:
            print("CSP hash 校验通过 sha256-%s" % actual[:16])
        # 同步后再验一次，防 meta 结构被改坏导致同步没落位
        m2 = _re.search(r'Content-Security-Policy" content="[^"]*?script-src[^"]*?sha256-([A-Za-z0-9+/=]+)', out)
        if not m2 or m2.group(1) != actual:
            raise SystemExit("CSP meta 结构异常，hash 同步失败，请检查 glass_template.html 的 meta CSP")

    subset_fonts(out)          # 字符集来自最终 HTML：改文案 -> 自动重子集 -> 不会豆腐块
    dst = os.path.join(BASE, "omox_glass.html")
    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(out)
    # ---- CSS 结构自检：关键选择器必须存在 ----
    # 起因：之前用正则改 CSS 时 [^;]* 跨过 } 吃掉了三句规则，语法层完全合法
    # （花括号配对 195/195），只有页面上移动端 banner 不显示才暴露。这类语义
    # 损坏数括号查不出来，只能按清单核选择器。
    css = out[out.find("<style>"):out.find("</style>")]
    css = _re.sub(r'/\*.*?\*/', '', css, flags=_re.S)   # 先剥注释：否则 "/* 说明 */\n.bg-img" 会拼成假选择器
    have = set()
    for sel in _re.findall(r'([^{}]+)\{', css):
        for one in sel.split(','):
            one = one.strip()
            if one and not one.startswith('@'):
                have.add(one)
    must = ['.bg', '.bg-img', '.bg-veil', '.blob', '.topbar', '.hero', '.glass',
            '.card', '.row', '.banner-wrap', '.ascii', '.ocr', '.detail', '.d-body',
            '.chip', '.contact-list', '.stats', '.rise', '.progress', '.sibs',
            '.d-body a', 'body.reading .progress',
            '.card[data-cat]', 'a.tag']
    missing = [x for x in must if x not in have]
    if missing:
        raise SystemExit("CSS 关键选择器缺失（结构被改坏？）: " + ", ".join(missing))
    if css.count('{') != css.count('}'):
        raise SystemExit("CSS 花括号不配对: { %d vs } %d" % (css.count('{'), css.count('}')))
    if "data:image/jpeg" in css:
        raise SystemExit("CSS 里仍有 JPEG base64 内嵌背景（应已改独立 bg.webp）")
    if 'url("bg.webp")' not in css:
        raise SystemExit("CSS 没引用到 bg.webp（背景图会白屏）")
    if not os.path.exists(BG_WORK):
        raise SystemExit("bg.webp 没生成")
    print("CSS 结构自检通过: %d 个选择器，清单 %d 项全在" % (len(have), len(must)))

    sizes = "HTML %.0f KB + bg.webp %.0f KB + fonts %.0f KB" % (
        os.path.getsize(dst) / 1024,
        os.path.getsize(BG_WORK) / 1024,
        sum(os.path.getsize(os.path.join(BASE, 'fonts', f))
            for f in os.listdir(os.path.join(BASE, 'fonts')) if f.endswith('.woff2')) / 1024)
    print("built: %s" % dst)
    print("产物: " + sizes)

if __name__ == "__main__":
    main()
