const fs=require('fs');const {JSDOM}=require('jsdom');
const html=fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html','utf8');
const manifest=[];
for(let i=1;i<=6;i++) manifest.push({stem:'shot_'+i,chat:'person_1',file:'by-chat/person_1/shot_'+i+'.jpg',thumb:'thumb/person_1/shot_'+i+'.jpg',type:(i%2?'image':'video'),date:'2026-01-0'+i,size:i*100000});
manifest.push({stem:'b1',chat:'person_2',file:'by-chat/person_2/b1.jpg',thumb:'thumb/person_2/b1.jpg',type:'image',date:'2026-02-01',size:50000});
const dom=new JSDOM(html,{runScripts:'dangerously',resources:'usable',beforeParse(window){
 window.fetch=(url)=>String(url).indexOf('manifest.json')>=0?Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(JSON.stringify(manifest)))}):Promise.resolve({status:200,json:()=>Promise.resolve({}),text:()=>Promise.resolve('')});
 window.alert=(m)=>{window.__a=m;};window.confirm=()=>true;window.prompt=()=>'NF';window.scrollTo=()=>{};
}});
const {window}=dom;const doc=window.document;
function click(el,opts){el.dispatchEvent(new window.MouseEvent('click',Object.assign({bubbles:true,cancelable:true},opts||{})));}
function key(k,opts){doc.dispatchEvent(new window.KeyboardEvent('keydown',Object.assign({key:k,bubbles:true,cancelable:true},opts||{})));}
setTimeout(()=>{ try{
 let p1=null;doc.querySelectorAll('#folderGrid .folder').forEach(f=>{if(f.dataset.chat==='person_1')p1=f;});
 click(p1);
 console.log('=== T1 SEARCH ===');
 let tiles=doc.querySelectorAll('#photoGrid .tile'); console.log('tiles in person_1:',tiles.length,'(expect 6)');
 const sb=doc.getElementById('searchBox'); sb.value='shot_3';
 sb.dispatchEvent(new window.Event('input',{bubbles:true}));
 setTimeout(()=>{
   let f=doc.querySelectorAll('#photoGrid .tile').length;
   console.log('tiles after search "shot_3":',f,'(expect 1)', f===1?'PASS':'FAIL');
   // clear search
   sb.value=''; sb.dispatchEvent(new window.Event('input',{bubbles:true}));
   setTimeout(()=>{
     console.log('=== T2 SHIFT-RANGE SELECT ===');
     tiles=doc.querySelectorAll('#photoGrid .tile');
     // click selbox 0 (anchor), then shift-click tile 3 -> expect 4 selected (0..3)
     click(tiles[0].querySelector('.selbox'));
     // shift-click on tile index 3 via the tile click handler with shiftKey
     click(tiles[3],{shiftKey:true});
     let selN=doc.querySelectorAll('#photoGrid .tile.selected').length;
     console.log('selected after anchor0 + shift-click3:',selN,'(expect 4)', selN===4?'PASS':'FAIL');
     console.log('=== T3 KEYBOARD Ctrl+A / Escape ===');
     key('a',{ctrlKey:true});
     let allN=doc.querySelectorAll('#photoGrid .tile.selected').length;
     console.log('after Ctrl+A selected:',allN,'(expect 6)', allN===6?'PASS':'FAIL');
     key('Escape');
     let afterEsc=doc.querySelectorAll('#photoGrid .tile.selected').length;
     console.log('after Escape selected:',afterEsc,'(expect 0)', afterEsc===0?'PASS':'FAIL');
     console.log('=== T4 CONTEXT MENU ===');
     tiles[0].dispatchEvent(new window.MouseEvent('contextmenu',{bubbles:true,cancelable:true,clientX:100,clientY:100}));
     let ctxShown=doc.getElementById('ctxMenu').classList.contains('show');
     let ctxBtns=doc.querySelectorAll('#ctxMenu button').length;
     console.log('context menu shown:',ctxShown,'buttons:',ctxBtns, (ctxShown&&ctxBtns>=5)?'PASS':'FAIL');
     console.log('=== T5 SORT name ===');
     const sort=doc.getElementById('sort'); sort.value='name'; sort.dispatchEvent(new window.Event('change',{bubbles:true}));
     let firstStem=doc.querySelector('#photoGrid .tile').dataset.stem;
     console.log('first tile after name-sort:',firstStem,'(expect shot_1)', firstStem==='shot_1'?'PASS':'FAIL');
   },200);
 },200);
}catch(e){console.log('EXCEPTION:',e.message,e.stack);} },800);
