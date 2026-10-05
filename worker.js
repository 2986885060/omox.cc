/* omox.cc 站点 Worker：
   - 静态资产由 Workers Static Assets 提供（wrangler [assets]，env.ASSETS）
   - 裸域 omox.cc 301 到 www（裸域此前回源 Caddy、还停在旧文件上）
   - 安全头在边缘统一补（meta CSP 管不到 frame-ancestors 这类响应头指令）
   - 缓存头：HTML 5 分钟、背景与字体一年 immutable —— 没有这步就没有"二访 32KB" */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 裸域一律去 www（前提是 omox.cc 也已 attach 到本 Worker）
    if (url.hostname === "omox.cc") {
      return Response.redirect("https://www.omox.cc" + url.pathname + url.search, 301);
    }

    const res = await env.ASSETS.fetch(request);
    if (res.status === 404 && url.pathname === "/") {
      // assets 入口缺失时给出可诊断的响应，而不是裸 404
      return new Response("index.html missing", { status: 404, headers: { "content-type": "text/plain" } });
    }

    const h = new Headers(res.headers);
    h.set("X-Content-Type-Options", "nosniff");
    h.set("Referrer-Policy", "strict-origin-when-cross-origin");
    h.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
    h.set("X-Frame-Options", "DENY");
    h.set("Content-Security-Policy", "frame-ancestors 'none'");
    h.set("Cross-Origin-Opener-Policy", "same-origin");

    const p = url.pathname;
    if (p === "/" || p.endsWith(".html")) {
      h.set("Cache-Control", "public, max-age=300, must-revalidate");
    } else if (p.startsWith("/bg.") || p.startsWith("/fonts/")) {
      h.set("Cache-Control", "public, max-age=31536000, immutable");
    }
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
  }
};
