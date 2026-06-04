const fs = require('fs');
const { JSDOM } = require('jsdom');

const html = fs.readFileSync('/Users/adam.durham/repos/homelab/ansible/roles/media_gallery/files/gallery_index.html', 'utf8');

// fake manifest: folder "person_1" with 3 items
const manifest = [
  {stem:'a1', chat:'person_1', file:'by-chat/person_1/a1.jpg', thumb:'thumbs/person_1/a1.jpg', type:'image', date:'2026-01-01'},
  {stem:'a2', chat:'person_1', file:'by-chat/person_1/a2.jpg', thumb:'thumbs/person_1/a2.jpg', type:'image', date:'2026-01-02'},
  {stem:'a3', chat:'person_1', file:'by-chat/person_1/a3.jpg', thumb:'thumbs/person_1/a3.jpg', type:'image', date:'2026-01-03'},
  {stem:'b1', chat:'person_2', file:'by-chat/person_2/b1.jpg', thumb:'thumbs/person_2/b1.jpg', type:'image', date:'2026-01-04'},
];

const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  resources: 'usable',
  beforeParse(window) {
    // stub fetch: manifest.json returns our manifest; everything else 200
    window.fetch = (url, opts) => {
      if (String(url).indexOf('manifest.json') >= 0) {
        return Promise.resolve({ ok:true, status:200, json:()=>Promise.resolve(manifest) });
      }
      return Promise.resolve({ status:200, json:()=>Promise.resolve({}), text:()=>Promise.resolve('') });
    };
    window.alert = (m)=>{ console.log('ALERT:', m); window.__lastAlert=m; };
    window.confirm = ()=>true;
    window.prompt = ()=>'NewFolder';
    window.scrollTo = ()=>{};
  }
});

const { window } = dom;
const doc = window.document;

function click(el){ el.dispatchEvent(new window.MouseEvent('click',{bubbles:true,cancelable:true})); }

setTimeout(() => {
  try {
    // 1. should be on landing with folder tiles
    const folders = doc.querySelectorAll('#folderGrid .folder:not(.newfolder)');
    console.log('TEST landing folders:', folders.length, '(expect >=2: person_1, person_2)');

    // 2. open person_1 by clicking its tile
    let p1=null;
    folders.forEach(f=>{ if((f.dataset.chat)==='person_1') p1=f; });
    if(!p1){ console.log('FAIL: no person_1 folder tile found'); return; }
    click(p1);

    // 3. now photo grid should have 3 tiles
    const tiles = doc.querySelectorAll('#photoGrid .tile');
    console.log('TEST photo tiles after open:', tiles.length, '(expect 3)');
    if(tiles.length===0){ console.log('FAIL: no tiles rendered'); return; }

    // 4. click the selbox on first 2 tiles
    const sb0 = tiles[0].querySelector('.selbox');
    const sb1 = tiles[1].querySelector('.selbox');
    console.log('TEST selbox exists on tile0:', !!sb0, 'tile1:', !!sb1);
    click(sb0); click(sb1);

    // 5. how many show selected + what does bulkCount say
    const selCount = doc.querySelectorAll('#photoGrid .tile.selected').length;
    const bulkCount = doc.getElementById('bulkCount').textContent;
    const bulkShown = doc.getElementById('bulkBar').classList.contains('show');
    console.log('TEST visually selected tiles:', selCount, '(expect 2)');
    console.log('TEST bulkCount text:', JSON.stringify(bulkCount), '(expect "2 selected")');
    console.log('TEST bulkBar shown:', bulkShown);

    // 6. click bulkMove -> does it say "nothing selected"?
    window.__lastAlert=null;
    click(doc.getElementById('bulkMove'));
    const menuShown = doc.getElementById('bulkMoveMenu').classList.contains('show');
    console.log('TEST after bulkMove click -> lastAlert:', window.__lastAlert, '| menu shown:', menuShown);
    if(window.__lastAlert && /select some items/i.test(window.__lastAlert)){
      console.log('>>> BUG REPRODUCED: says nothing selected despite', selCount, 'selected <<<');
    } else if(menuShown){
      console.log('>>> move menu opened correctly with destinations <<<');
    }
  } catch(e){ console.log('EXCEPTION:', e.message, e.stack); }
}, 800);
