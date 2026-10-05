"""Progressive public disclosure for Blyg generated-text markers.

Protocol content keeps only ``blyg-tk-gen`` and ``generated[]``.  This module
adds a human-page robot button and an accessible, self-reported disclosure
without changing either wire representation.
"""
import html, json, re

ROBOT='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2224%22 height=%2224%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%23111%22 stroke-width=%221.7%22 stroke-linecap=%22round%22 stroke-linejoin=%22round%22%3E%3Cpath d=%22M12 8V4H8%22/%3E%3Crect width=%2216%22 height=%2212%22 x=%224%22 y=%228%22 rx=%222%22/%3E%3Cpath d=%22M2 14h2M20 14h2M15 13v2M9 13v2%22/%3E%3C/svg%3E'

STYLE='<style id="blynger-generation-disclosure-style">.blyg-tk-gen{position:relative;background:#f2f2f2;border:1px dashed #505050;margin:1em 0 1.4em;padding:.65em .8em 1.15em}.blyg-tk-gen.gen-ready::after{display:none}.blyg-tk-gen>.blynger-gen-badge{position:absolute;box-sizing:border-box;left:.65em;bottom:-14px;width:30px;height:27px;margin:0;padding:0;border:1px solid #444;background:#fff center/20px 20px no-repeat url("'+ROBOT+'");cursor:pointer}.blyg-tk-gen>.blynger-gen-badge:focus-visible{outline:2px solid #222;outline-offset:2px}.blynger-gen-pop{position:fixed;z-index:1000;box-sizing:border-box;width:max-content;max-width:min(20rem,calc(100vw - 1rem));padding:.65rem .8rem;background:#fff;color:#222;border:1px solid #555;box-shadow:5px 5px 0 #0003;font:13px/1.45 Tahoma,Verdana,sans-serif}.blynger-gen-pop[hidden]{display:none}.blynger-gen-pop p{margin:0 0 .45rem}.blynger-gen-pop p:last-child{margin-bottom:0}.blynger-gen-pop strong{display:block;margin-bottom:.2rem}.blynger-gen-pop dl{display:grid;grid-template-columns:auto 1fr;gap:.1rem .6rem;margin:.4rem 0 0}.blynger-gen-pop dt{color:#666}.blynger-gen-pop dd{margin:0;overflow-wrap:anywhere}</style>'

SCRIPT='''<script id="blynger-generation-disclosure-script">(function(){
if(!document.querySelector('.blyg-tk-gen'))return;var pop,current,pinned=false,timer;
function add(p,t,x){var e=document.createElement(t);e.textContent=x;p.appendChild(e);return e}
function decorate(e){if(e.classList.contains('gen-ready'))return;var b=document.createElement('button');b.type='button';b.className='blynger-gen-badge';b.setAttribute('aria-label','AI-generated text: what the author disclosed');b.setAttribute('aria-expanded','false');e.insertBefore(b,e.firstChild);e.classList.add('gen-ready')}
function fill(b){pop.textContent='';var box=b.parentNode;var h=add(pop,'strong','AI-generated');if(box.closest('blockquote.blyg-transclusion')){add(pop,'p','The quoted author marked this text as machine-generated. Its details are in the quoted item.');return}add(pop,'p','The author marked this text as machine-generated. Self-reported, not verified.');var holder=box.closest('[data-generated]'),list=[];try{list=holder?JSON.parse(holder.getAttribute('data-generated'))||[]:[]}catch(e){}var models=[],dates=[],sources={};list.forEach(function(g){if(!g)return;if(g.model&&models.indexOf(g.model)<0)models.push(g.model);if(g.at)dates.push(g.at);(g.sources||[]).forEach(function(s){var k=s&&(s.id||s.url||JSON.stringify(s));if(k)sources[k]=1})});dates.sort();var dl=document.createElement('dl');pop.appendChild(dl);add(dl,'dt',models.length>1?'Models':'Model');add(dl,'dd',models.length?models.join(', '):'not stated');if(dates.length){var first=new Date(dates[0]),last=new Date(dates[dates.length-1]);var fmt=function(d,raw){return isNaN(d)?raw:d.toLocaleDateString(undefined,{year:'numeric',month:'short',day:'numeric'})};var a=fmt(first,dates[0]),z=fmt(last,dates[dates.length-1]);add(dl,'dt','Generated');add(dl,'dd',a===z?a:a+' to '+z)}var n=Object.keys(sources).length;if(n){add(dl,'dt','Drew on');add(dl,'dd',n+(n===1?' item':' items'))}if(list.length>1)add(pop,'p','These details cover all '+list.length+' generated passages in this version.')}
function place(b){var r=b.getBoundingClientRect(),w=pop.offsetWidth,h=pop.offsetHeight;pop.style.left=Math.min(Math.max(8,r.left),innerWidth-w-8)+'px';var top=r.bottom+6;if(top+h>innerHeight-8)top=Math.max(8,r.top-h-6);pop.style.top=top+'px'}
function open(b,keep){clearTimeout(timer);if(!pop){pop=document.createElement('div');pop.className='blynger-gen-pop';pop.id='blynger-gen-pop';pop.setAttribute('role','tooltip');pop.hidden=true;document.body.appendChild(pop);pop.onmouseenter=function(){clearTimeout(timer)};pop.onmouseleave=function(){if(!pinned)later()}}if(current&&current!==b)current.setAttribute('aria-expanded','false');current=b;pinned=keep;fill(b);pop.hidden=false;place(b);b.setAttribute('aria-expanded','true');b.setAttribute('aria-describedby',pop.id)}
function close(){clearTimeout(timer);if(pop)pop.hidden=true;if(current)current.setAttribute('aria-expanded','false');current=null;pinned=false}function later(){clearTimeout(timer);timer=setTimeout(close,200)}function badge(e){return e.target.closest&&e.target.closest('.blynger-gen-badge')}
document.querySelectorAll('.blyg-tk-gen').forEach(decorate);document.addEventListener('click',function(e){var b=badge(e);if(b){e.preventDefault();if(pinned&&current===b)close();else open(b,true)}else if(pop&&!pop.hidden&&!pop.contains(e.target))close()});document.addEventListener('mouseover',function(e){var b=badge(e);if(b&&!pinned)open(b,false)});document.addEventListener('mouseout',function(e){if(badge(e)&&!pinned)later()});document.addEventListener('focusin',function(e){var b=badge(e);if(b&&!pinned)open(b,false)});document.addEventListener('focusout',function(e){if(badge(e)&&!pinned)later()});document.addEventListener('keydown',function(e){if(e.key==='Escape')close()});addEventListener('scroll',function(){if(current&&pop&&!pop.hidden)place(current)},{passive:true});addEventListener('resize',function(){if(current&&pop&&!pop.hidden)place(current)});
})();</script>'''

def decorate(raw,generated):
    """Add progressive disclosure to one newly rendered human HTML page."""
    if 'blyg-tk-gen' not in raw:return raw
    # A pre-robot generation style is part of that historical page's design.
    # Explicitly touching its prose does not silently restyle the old passage.
    old_style=re.search(r'<style\b[^>]*id=["\']blynger-generation-style["\'][^>]*>(.*?)</style>',raw,re.I|re.S)
    if old_style and 'data:image/svg+xml' not in old_style.group(1):return raw
    payload=html.escape(json.dumps(generated or [],ensure_ascii=False,separators=(',',':')),quote=True)
    def article(match):
        tag=match.group()
        if re.search(r'\sdata-generated=',tag,re.I):
            return re.sub(r'\sdata-generated=(["\']).*?\1',' data-generated="'+payload+'"',tag,count=1,flags=re.I)
        return tag[:-1]+' data-generated="'+payload+'">'
    raw=re.sub(r'<article\b[^>]*>',article,raw,count=1,flags=re.I)
    if 'id="blynger-generation-disclosure-style"' not in raw:
        raw=re.sub(r'</head\s*>',STYLE+r'\g<0>',raw,count=1,flags=re.I)
    if 'id="blynger-generation-disclosure-script"' not in raw:
        raw=re.sub(r'</body\s*>',SCRIPT+r'\g<0>',raw,count=1,flags=re.I) if re.search(r'</body\s*>',raw,re.I) else raw+SCRIPT
    return raw
