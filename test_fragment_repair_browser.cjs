const {chromium}=require('playwright');
const path=require('path');

(async()=>{
  const browser=await chromium.launch({executablePath:'/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',headless:true});
  try {
    const page=await browser.newPage();
    await page.setContent('<section><div id="editor" contenteditable="true"><h1>Title</h1><p>First fragment.</p><p>Second fragment.</p><p>Last paragraph.</p><p>—Example Author<br>October 2, 2026</p></div></section>');
    await page.addScriptTag({content:'function publicImages(s){return s;}'});
    await page.addScriptTag({path:path.join(__dirname,'static/fragments.js')});
    const result=await page.evaluate(()=>{
      const notices=[],editor=document.getElementById('editor');
      const f=new FragmentEditor(editor,()=>{},message=>notices.push(message));
      const at=el=>{const r=document.createRange();r.selectNodeContents(el);r.collapse(true);getSelection().removeAllRanges();getSelection().addRange(r);};
      at(editor.children[2]);f.addDivider();
      const before=f.snapshot(),lost=before.dividers[0],oldKey=before.ranges.find(r=>r.start===lost).key;
      editor.querySelector('[data-fragment-block="'+lost+'"]').remove();
      editor.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'deleteContentBackward'}));
      const after=f.snapshot(),ids=new Set(after.blocks.map(block=>block.id));
      return {after,lost,oldKey,notices,allDividersLive:after.dividers.every(id=>ids.has(id))};
    });
    if(result.after.dividers.includes(result.lost)||!result.allDividersLive)throw Error('Deleted divider was not repaired');
    if(!result.after.ranges.some(range=>range.key===result.oldKey))throw Error('Repair lost fragment identity');
    if(!result.notices.some(message=>message.includes('repaired')))throw Error('Repair was not explained');
    const headings=await page.evaluate(()=>{
      const editor=document.getElementById('editor'),notices=[];
      editor.innerHTML='<h1>Title</h1><p>Introduction.</p><p><ul><li>List thought.</li></ul><h2>Second thought</h2><p>Body two.</p><h2>Third thought</h2><p>Body three.</p></p>';
      const meta={version:1,blocks:[
        {id:'title',html:'<h1>Title</h1>'},
        {id:'intro',html:'<p>Introduction.</p>'},
        {id:'legacy',html:'<p><ul><li>List thought.</li></ul><h2>Second thought</h2><p>Body two.</p><h2>Third thought</h2><p>Body three.</p></p>'}
      ],dividers:['intro','legacy'],ranges:[{key:'intro-key',start:'intro',end:'legacy'},{key:'legacy-key',start:'legacy',end:null}]};
      let dirty=0;const f=new FragmentEditor(editor,()=>dirty++,message=>notices.push(message));f.load(meta);const after=f.snapshot();
      const h2=[...editor.querySelectorAll(':scope > h2')].map(el=>el.dataset.fragmentBlock);
      return {after,h2,dirty,notices,text:editor.innerText};
    });
    if(headings.h2.length!==2||!headings.h2.every(id=>headings.after.dividers.includes(id)))throw Error('Repaired H2 did not become fragment boundaries');
    if(!headings.after.ranges.some(range=>range.key==='legacy-key'))throw Error('Expanded legacy block lost fragment identity');
    if(headings.dirty!==1||!headings.notices.some(message=>message.includes('H2 headings')))throw Error('Automatic structural repair was not surfaced as an unsaved change');
    if(!headings.text.includes('List thought.')||!headings.text.includes('Body three.'))throw Error('Structural repair lost authored prose');
    console.log('Browser checks passed: deleted boundaries self-repair, malformed blocks expand safely, and every H2 becomes a fragment boundary.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
