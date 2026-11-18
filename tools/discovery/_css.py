# SPDX-License-Identifier: MIT
"""发现页内联样式表与视觉设计令牌（零外部子资源，支持浅色/深色/跟随系统）。"""

from __future__ import annotations

_CSS = """
*,*::before,*::after{box-sizing:border-box}
:root,html[data-theme="light"]{
--bg:#f4f8f6;--panel:#ffffff;--panel-2:#ecf3ef;--text:#11241e;--muted:#566b63;
--line:#d7e3dd;--line-soft:#e6efe9;--line-strong:#bfd2c9;
--accent:#0f6e56;--accent-hover:#138266;--accent-soft:#dff2ec;--accent-glow:rgba(15,110,86,.13);--accent-line:rgba(15,110,86,.45);
--brand:#0f3d2e;--grid-line:rgba(15,61,46,.042);
--official:#166d3b;--reviewed:#0b60c4;--recipe:#5b3fa8;--recipe-soft:#eeeafb;
--high:#b54708;--medium:#8a6d00;--low:#566b63;
--header-bg:rgba(244,248,246,.82);--toolbar-bg:rgba(255,255,255,.86);
--shadow:0 1px 2px rgba(15,52,41,.05),0 10px 28px rgba(15,52,41,.06);
--shadow-hover:0 4px 12px rgba(15,52,41,.08),0 16px 36px rgba(15,52,41,.10);
color-scheme:light;
}
html[data-theme="dark"]{
--bg:#0d1512;--panel:#14201c;--panel-2:#1a2924;--text:#eaf4f0;--muted:#94ada4;
--line:#263932;--line-soft:#1d2d27;--line-strong:#385449;
--accent:#4cc3a5;--accent-hover:#6bd1b7;--accent-soft:#193830;--accent-glow:rgba(76,195,165,.15);--accent-line:rgba(76,195,165,.5);
--brand:#dff7e4;--grid-line:rgba(234,244,240,.038);
--official:#2ea043;--reviewed:#4493f8;--recipe:#b59dff;--recipe-soft:#251f3a;
--high:#e3813a;--medium:#d4b03a;--low:#94ada4;
--header-bg:rgba(13,21,18,.82);--toolbar-bg:rgba(20,32,28,.88);
--shadow:0 1px 2px rgba(0,0,0,.42),0 12px 30px rgba(0,0,0,.34);
--shadow-hover:0 6px 16px rgba(0,0,0,.48),0 20px 42px rgba(0,0,0,.42);
color-scheme:dark;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
--bg:#0d1512;--panel:#14201c;--panel-2:#1a2924;--text:#eaf4f0;--muted:#94ada4;
--line:#263932;--line-soft:#1d2d27;--line-strong:#385449;
--accent:#4cc3a5;--accent-hover:#6bd1b7;--accent-soft:#193830;--accent-glow:rgba(76,195,165,.15);--accent-line:rgba(76,195,165,.5);
--brand:#dff7e4;--grid-line:rgba(234,244,240,.038);
--official:#2ea043;--reviewed:#4493f8;--recipe:#b59dff;--recipe-soft:#251f3a;
--high:#e3813a;--medium:#d4b03a;--low:#94ada4;
--header-bg:rgba(13,21,18,.82);--toolbar-bg:rgba(20,32,28,.88);
--shadow:0 1px 2px rgba(0,0,0,.42),0 12px 30px rgba(0,0,0,.34);
--shadow-hover:0 6px 16px rgba(0,0,0,.48),0 20px 42px rgba(0,0,0,.42);
color-scheme:dark;
}}
html{-webkit-text-size-adjust:100%}
body{margin:0;color:var(--text);background:radial-gradient(1200px 460px at 12% -10%,var(--accent-soft),transparent 66%),var(--bg);
font:16px/1.64 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,sans-serif}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
code,kbd{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;font-size:.86em}
kbd{display:inline-block;padding:.08rem .44rem;border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:6px;background:var(--panel);color:var(--text);font-size:.78em;font-weight:600;line-height:1.35}
.wrap{max-width:1160px;margin:0 auto;padding:1.25rem 1.25rem 3.5rem}
.skip{position:absolute;left:-9999px}
.skip:focus{left:1rem;top:1rem;background:var(--panel);color:var(--text);padding:.55rem .9rem;border-radius:10px;z-index:30}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
.site-head{position:sticky;top:0;z-index:20;background:var(--header-bg);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.head-inner{max-width:1160px;margin:0 auto;padding:.65rem 1.25rem;display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}
.brand{display:inline-flex;align-items:center}
.logo svg{display:block;width:min(228px,50vw);height:auto}
.logo .wm-dark{display:none}
html[data-theme="dark"] .logo .wm-light{display:none}
html[data-theme="dark"] .logo .wm-dark{display:block}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .logo .wm-light{display:none}:root:not([data-theme="light"]) .logo .wm-dark{display:block}}
.site-nav{display:flex;align-items:center;gap:.45rem;font-size:.9rem;flex-wrap:wrap}
.nav-link{color:var(--muted);font-weight:500;padding:.32rem .72rem;border-radius:999px;border:1px solid transparent}
.nav-link:hover{color:var(--text);background:var(--panel-2);text-decoration:none}
.nav-link[aria-current="page"]{color:var(--accent);background:var(--accent-soft);border-color:var(--line);font-weight:600}
.theme-btn{font:inherit;font-size:.82rem;font-weight:500;color:var(--text);background:var(--panel);border:1px solid var(--line);
border-radius:999px;padding:.3rem .78rem;cursor:pointer;margin-left:.2rem}
.theme-btn:hover{border-color:var(--accent);color:var(--accent)}
.eyebrow{margin:0 0 .45rem;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.73rem;font-weight:700;letter-spacing:.08em;color:var(--accent)}
h1{margin:.1rem 0 .6rem;font-size:clamp(1.65rem,2.8vw,2.32rem);letter-spacing:-.025em;line-height:1.2}
h2{margin:0 0 .9rem;font-size:1.04rem;letter-spacing:-.01em;display:flex;align-items:center;gap:.5rem;flex-wrap:wrap}
h3{margin:.95rem 0 .45rem;font-size:.95rem}
.page-title{margin-top:.1rem;display:flex;align-items:center;gap:.55rem;flex-wrap:wrap}
.lede{margin:0;max-width:74ch;color:var(--muted);font-size:.97rem}
.lede strong{color:var(--text)}
.hero{position:relative;overflow:hidden;background-color:var(--panel);
background-image:radial-gradient(680px 260px at 90% 0%,var(--accent-glow),transparent 72%),radial-gradient(520px 220px at 6% 100%,var(--accent-soft),transparent 78%),linear-gradient(to right,var(--grid-line) 1px,transparent 1px),linear-gradient(to bottom,var(--grid-line) 1px,transparent 1px);
background-size:100% 100%,100% 100%,28px 28px,28px 28px;
border:1px solid var(--line-strong);border-radius:20px;padding:1.7rem 1.75rem 1.6rem;margin:.35rem 0 1.35rem;box-shadow:var(--shadow)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(136px,1fr));gap:.65rem;margin:1.45rem 0 0;padding:0}
.stats>div{background:var(--panel);border:1px solid var(--line);border-top:2px solid var(--accent-line);border-radius:12px;padding:.68rem .88rem;box-shadow:var(--shadow)}
.stats dt{color:var(--muted);font-size:.75rem;font-weight:500;letter-spacing:.03em}
.stats dd{margin:.24rem 0 0;font-weight:700;font-size:1.28rem;letter-spacing:-.02em;font-variant-numeric:tabular-nums;word-break:break-all}
.cta{display:flex;flex-wrap:wrap;gap:.55rem;margin:1.3rem 0 0}
.btn{display:inline-flex;align-items:center;gap:.35rem;background:var(--brand);color:#fff;border:1px solid var(--brand);border-radius:10px;padding:.5rem 1rem;font-size:.9rem;font-weight:600}
html[data-theme="dark"] .btn{background:var(--accent);color:#081612;border-color:var(--accent)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .btn{background:var(--accent);color:#081612;border-color:var(--accent)}}
.btn-ghost{background:var(--panel);color:var(--text);border-color:var(--line);font-weight:500}
html[data-theme="dark"] .btn-ghost{background:var(--panel-2);color:var(--text);border-color:var(--line)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .btn-ghost{background:var(--panel-2);color:var(--text);border-color:var(--line)}}
.btn:hover{text-decoration:none;border-color:var(--accent)}
.btn-ghost:hover{background:var(--accent-soft);color:var(--accent)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:1.1rem 1.25rem;margin:1.2rem 0;box-shadow:var(--shadow)}
.grid-2{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:1.2rem}
.note{color:var(--muted);font-size:.9rem;margin:.5rem 0}
.hint{color:var(--muted);font-size:.8rem;font-weight:400}
details{margin:.15rem 0}
details>summary{cursor:pointer;color:var(--accent);font-size:.92rem;font-weight:500;width:fit-content}
details.panel>summary{color:var(--text);font-weight:600;font-size:1rem}
details>summary::marker{color:var(--muted)}
.list-hero{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem 1.4rem;flex-wrap:wrap;padding:.35rem 0 .2rem}
.seg-tabs{display:inline-flex;flex-wrap:wrap;gap:.28rem;background:var(--panel-2);border:1px solid var(--line);border-radius:12px;padding:.26rem}
.seg-tab{font:inherit;font-size:.86rem;font-weight:500;color:var(--muted);background:transparent;border:1px solid transparent;border-radius:9px;padding:.36rem .78rem;cursor:pointer;display:inline-flex;align-items:center;gap:.38rem}
.seg-tab:hover{color:var(--text)}
.seg-tab.is-active{background:var(--panel);color:var(--accent);border-color:var(--line);font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.seg-num{font-size:.74rem;font-variant-numeric:tabular-nums;background:var(--accent-soft);color:var(--accent);border-radius:999px;padding:.02rem .44rem;font-weight:600}
.toolbar{position:sticky;top:3.65rem;z-index:12;display:flex;flex-wrap:wrap;gap:.75rem .95rem;align-items:flex-end;
background:var(--toolbar-bg);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:1px solid var(--line);border-radius:16px;
padding:.85rem 1.05rem;margin:1rem 0 .85rem;box-shadow:var(--shadow)}
.field{display:flex;flex-direction:column;gap:.28rem}
.field-search{flex:1 1 17rem}
.search-wrap{position:relative;display:flex;align-items:center}
.search-wrap input{width:100%;padding-right:2.2rem}
.search-kbd{position:absolute;right:.55rem;pointer-events:none;opacity:.78}
.search-wrap:focus-within .search-kbd{opacity:0}
.lbl{font-size:.74rem;font-weight:600;letter-spacing:.04em;color:var(--muted)}
input,select{font:inherit;font-size:.9rem;color:var(--text);background:var(--panel);border:1px solid var(--line);
border-radius:10px;padding:.46rem .68rem;min-width:10.2rem;max-width:100%}
input:hover,select:hover{border-color:var(--line-strong)}
input:focus,select:focus{border-color:var(--accent);outline:none;box-shadow:0 0 0 3px var(--accent-glow)}
input[type=search]{min-width:15rem}
.btn-reset{font:inherit;font-size:.85rem;font-weight:600;color:var(--accent);background:var(--accent-soft);border:1px solid var(--accent);
border-radius:10px;padding:.46rem .82rem;cursor:pointer}
.btn-reset:hover{background:var(--accent);color:#fff}
.live{margin:0 0 .35rem auto;color:var(--muted);font-size:.85rem;font-weight:500;font-variant-numeric:tabular-nums}
.tag-bar{display:flex;flex-wrap:wrap;align-items:center;gap:.42rem;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:.62rem .92rem;margin:0 0 1.45rem;box-shadow:var(--shadow)}
.tag-bar-label{font-size:.75rem;font-weight:600;letter-spacing:.04em;color:var(--muted);margin-right:.2rem}
.tag-chip{font:inherit;font-size:.79rem;font-weight:500;color:var(--muted);background:var(--panel-2);border:1px solid var(--line);border-radius:999px;padding:.22rem .68rem;cursor:pointer;display:inline-flex;align-items:center;gap:.34rem;line-height:1.4}
.tag-chip:hover{color:var(--accent);border-color:var(--accent);background:var(--accent-soft)}
.tag-chip.is-active{color:#fff;background:var(--accent);border-color:var(--accent);font-weight:600}
html[data-theme="dark"] .tag-chip.is-active{color:#081612;background:var(--accent);border-color:var(--accent)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .tag-chip.is-active{color:#081612;background:var(--accent);border-color:var(--accent)}}
.tag-chip-num{font-size:.7rem;font-variant-numeric:tabular-nums;opacity:.82}
.home-tags{display:flex;flex-wrap:wrap;gap:.38rem;margin:.35rem 0 0}
.home-tag-link{display:inline-flex;align-items:center;gap:.3rem;font-size:.78rem;font-weight:500;color:var(--muted);background:var(--panel-2);border:1px solid var(--line);border-radius:999px;padding:.2rem .64rem}
.home-tag-link:hover{color:var(--accent);border-color:var(--accent);background:var(--accent-soft);text-decoration:none}
.group{margin:0 0 2.2rem}
.count{background:var(--panel-2);color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:.05rem .56rem;font-size:.78rem;font-weight:600;font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(316px,1fr));gap:1rem}
.card{display:flex;flex-direction:column;gap:.52rem;background:var(--panel);border:1px solid var(--line);
border-radius:16px;padding:1.05rem 1.1rem 1rem;box-shadow:var(--shadow);break-inside:avoid}
.card-head{display:flex;align-items:flex-start;gap:.6rem;justify-content:space-between}
.card h3{margin:0;font-size:1.03rem;line-height:1.36;letter-spacing:-.01em;word-break:break-word}
.card h3 a{color:var(--text)}
.card h3 a:hover{color:var(--accent);text-decoration:none}
.ver{flex:none;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.75rem;font-weight:600;color:var(--accent);background:var(--accent-soft);border:1px solid var(--line);
border-radius:999px;padding:.08rem .52rem;font-variant-numeric:tabular-nums}
.card-id{margin:0;color:var(--muted);font-size:.8rem;word-break:break-all;display:flex;flex-wrap:wrap;gap:.42rem;align-items:center}
.card-id code{background:var(--panel-2);border:1px solid var(--line-soft);border-radius:6px;padding:.06rem .38rem}
.kind-pill{display:inline-flex;align-items:center;font-size:.7rem;font-weight:600;border-radius:6px;padding:.05rem .42rem;background:var(--panel-2);color:var(--muted);border:1px solid var(--line-soft)}
.kind-component{background:var(--recipe-soft);color:var(--recipe);border-color:var(--line)}
.badges{margin:0;display:flex;flex-wrap:wrap;gap:.35rem;align-items:center}
.b{display:inline-flex;align-items:center;padding:.1rem .52rem;border-radius:999px;font-size:.74rem;font-weight:600;line-height:1.48;white-space:nowrap}
.b-official{background:var(--official);color:#fff}
.b-reviewed{background:var(--reviewed);color:#fff}
.b-recipe{background:var(--recipe-soft);color:var(--recipe);border:1px solid var(--recipe);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-weight:600}
.b-high{background:var(--high);color:#fff}
.b-pub{background:var(--panel-2);color:var(--muted);border:1px solid var(--line-soft);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-weight:500}
.b-risk{background:var(--panel-2);border:1px solid var(--line);font-weight:500}
.b-risk-high{color:var(--high);border-color:var(--high)}
.b-risk-medium{color:var(--medium);border-color:var(--medium)}
.b-risk-low{color:var(--muted)}
.summary{margin:0;font-size:.92rem;color:var(--text);line-height:1.56}
.tags{margin:0;display:flex;flex-wrap:wrap;gap:.32rem}
.tag,.chip{display:inline-block;font-size:.73rem;padding:.08rem .46rem;border-radius:7px;background:var(--panel-2);border:1px solid var(--line-soft);color:var(--muted)}
.tag-btn{font:inherit;font-size:.73rem;cursor:pointer;line-height:1.45}
.tag-btn:hover{color:var(--accent);border-color:var(--accent);background:var(--accent-soft)}
.tag-btn.is-active{color:var(--accent);border-color:var(--accent);background:var(--accent-soft);font-weight:600}
.chip{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.72rem}
.meta{margin:auto 0 0;padding-top:.56rem;border-top:1px solid var(--line-soft);display:flex;flex-wrap:wrap;gap:.35rem .2rem;color:var(--muted);font-size:.77rem;font-variant-numeric:tabular-nums}
.k{color:var(--muted)}
.meta .k+.k::before{content:"·";margin:0 .38rem;color:var(--line-strong)}
.facts{margin:.25rem 0 .3rem;display:grid;grid-template-columns:minmax(7.5rem,auto) 1fr;gap:0 .95rem;font-size:.86rem}
.facts dt,.facts dd{padding:.42rem 0;border-bottom:1px solid var(--line-soft)}
.facts dt{color:var(--muted);font-weight:500;white-space:nowrap}
.facts dd{margin:0;display:flex;flex-wrap:wrap;gap:.32rem;align-items:baseline;word-break:break-word}
.hash{word-break:break-all;font-size:.76rem;color:var(--muted);background:var(--panel-2);border:1px solid var(--line-soft);border-radius:6px;padding:.08rem .38rem}
.artifact-list{list-style:none;margin:.35rem 0 .65rem;padding:0;display:grid;gap:.55rem}
.artifact-list li{background:var(--panel-2);border:1px solid var(--line);border-radius:12px;padding:.65rem .9rem;font-size:.84rem;word-break:break-all}
.crumbs{margin:.15rem 0 .95rem;color:var(--muted);font-size:.86rem;display:flex;gap:.55rem;flex-wrap:wrap;align-items:center}
.crumbs a{font-weight:500}
.crumbs span::before{content:"/";margin-right:.55rem;color:var(--line-strong)}
.detail-head{background:var(--panel);border:1px solid var(--line-strong);border-radius:18px;padding:1.35rem 1.45rem;margin:0 0 1.25rem;box-shadow:var(--shadow);display:grid;gap:.55rem}
.detail-head h1{margin:0}
.detail-head .meta{margin:0;padding-top:.5rem}
.copy{font:inherit;font-size:.76rem;font-weight:600;color:var(--text);background:var(--panel);border:1px solid var(--line-strong);
border-radius:8px;padding:.16rem .58rem;cursor:pointer}
.copy:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-soft)}
.risk-line{display:flex;align-items:center;gap:.55rem;margin:.2rem 0 .65rem;flex-wrap:wrap}
.empty-doc{margin:0;color:var(--muted);background:var(--panel-2);border:1px dashed var(--line-strong);border-radius:12px;padding:.85rem 1.05rem}
.cat-list{list-style:none;margin:0;padding:0;display:grid;gap:.48rem}
.cat-list a{display:flex;justify-content:space-between;gap:.6rem;align-items:center;background:var(--panel-2);
border:1px solid var(--line);border-radius:11px;padding:.5rem .78rem;font-size:.9rem;font-weight:500;color:var(--text)}
.cat-list a:hover{border-color:var(--accent);background:var(--accent-soft);text-decoration:none}
.cat-list h3{margin:.85rem 0 .4rem;font-size:.88rem;color:var(--muted)}
.mini-list{list-style:none;margin:0;padding:0;display:grid;gap:.5rem}
.mini-list a{display:grid;grid-template-columns:1fr auto;gap:.28rem .65rem;align-items:center;background:var(--panel-2);
border:1px solid var(--line);border-radius:12px;padding:.58rem .82rem;color:var(--text)}
.mini-list a:hover{border-color:var(--accent);text-decoration:none}
.mini-name{font-size:.93rem;font-weight:600}
.mini-meta{color:var(--muted);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.76rem;font-variant-numeric:tabular-nums}
.mini-summary{grid-column:1/-1;color:var(--muted);font-size:.83rem;line-height:1.45}
.mini-badges{grid-column:1/-1;display:flex;gap:.32rem;flex-wrap:wrap}
.tomb-list{list-style:none;margin:0;padding:0;display:grid;gap:.5rem}
.tomb-list li{background:var(--panel-2);border:1px solid var(--line);border-radius:12px;padding:.65rem .85rem;display:flex;flex-wrap:wrap;gap:.6rem}
.tomb-list .why{color:var(--muted);font-size:.9rem}
.nomatch{background:var(--panel);border:1px dashed var(--line-strong);border-radius:16px;padding:1.6rem;text-align:center;color:var(--muted)}
.md{margin:.25rem 0 0;font-size:.95rem;line-height:1.68}
.md h2,.md h3,.md h4{margin:1.35rem 0 .5rem;font-size:1.02rem;letter-spacing:-.01em}
.md h2:first-child,.md h3:first-child{margin-top:.2rem}
.md p{margin:.6rem 0}
.md ul,.md ol{margin:.55rem 0;padding-left:1.35rem}
.md li{margin:.24rem 0}
.md blockquote{margin:.75rem 0;padding:.45rem .95rem;border-left:3px solid var(--accent);background:var(--panel-2);border-radius:0 10px 10px 0;color:var(--muted)}
.md hr{border:0;border-top:1px solid var(--line);margin:1.15rem 0}
.md pre.code{background:var(--panel-2);border:1px solid var(--line);border-radius:12px;padding:.8rem 1rem;overflow-x:auto;line-height:1.55}
.md pre.code code{font-size:.82rem;background:none;border:0;padding:0}
.md code{background:var(--panel-2);border:1px solid var(--line-soft);border-radius:5px;padding:.05rem .34rem}
.table-wrap{overflow-x:auto;margin:.75rem 0;border:1px solid var(--line);border-radius:10px}
.md table{border-collapse:collapse;width:100%;font-size:.86rem}
.md th,.md td{border-bottom:1px solid var(--line);padding:.48rem .65rem;text-align:left;vertical-align:top}
.md tr:last-child td{border-bottom:0}
.md th{background:var(--panel-2);font-weight:600;white-space:nowrap}
footer{border-top:1px solid var(--line);margin-top:2rem;padding-top:1.15rem}
@media (prefers-reduced-motion:no-preference){
.card,.mini-list a,.cat-list a,.btn,.seg-tab,.tag-chip,.tag-btn,.home-tag-link,.theme-btn,.copy{transition:transform .18s cubic-bezier(.2,.8,.2,1),border-color .18s ease,box-shadow .18s ease,background-color .15s ease,color .15s ease}
.card:hover{transform:translateY(-2px);border-color:var(--accent);box-shadow:var(--shadow-hover)}
.mini-list a:hover,.cat-list a:hover{transform:translateY(-1px)}
}
@media (max-width:720px){.toolbar{position:static}.list-hero{align-items:flex-start}}
[hidden]{display:none!important}
@media print{.site-head,.toolbar,.tag-bar,.seg-tabs,.copy,.site-nav{display:none}.card,.hero,.detail-head,.panel{box-shadow:none}}
"""
