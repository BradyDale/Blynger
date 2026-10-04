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
    console.log('Browser check passed: deleted fragment boundaries repair themselves without losing prose or identity.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
