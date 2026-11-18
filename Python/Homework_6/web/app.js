'use strict';
const $ = id => document.getElementById(id);
const courier = document.documentElement.dataset.role === 'courier';
const stages = ['Оформлен', 'Курьер идёт в ресторан', 'В пути к клиенту', 'Доставлен'];
const actions = ['Принять заказ', 'Забрал заказ', 'Доставил'];
const escapeHtml = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let catalog, orders = [], online = false, busy = false, generation = 0;
const telegram = window.Telegram?.WebApp;
if (telegram) { telegram.ready(); telegram.expand(); }
const sessionHeaders = {};
if (!courier && telegram?.initData) {
  sessionHeaders['X-Telegram-Init'] = telegram.initData;
}
let draft = JSON.parse(localStorage.getItem('draft') || '{}');
const save = () => localStorage.setItem('draft', JSON.stringify(draft));
async function api(path, data) {
  const res = await fetch('/api/' + path, data === undefined ? {headers:sessionHeaders} : {
    method:'POST', headers:{...sessionHeaders,'Content-Type':'application/json'}, body:JSON.stringify(data)
  });
  const body = await res.json();
  if (!res.ok) throw Object.assign(Error(body.error), {status:res.status});
  return body;
}
function options(values, selected) {
  return values.map(v => '<option' + (v === selected ? ' selected' : '') + '>' + escapeHtml(v) + '</option>').join('');
}
function client() {
  if (!catalog.shops[draft.shop]) { draft.shop=Object.keys(catalog.shops)[0]; draft.items={}; delete draft.token; }
  if (!catalog.places[draft.address]) draft.address=catalog.addresses[2];
  draft.items ||= {};
  const shop = catalog.shops[draft.shop];
  $('content').innerHTML = '<form id="form" class="grid"><div class="card"><h2>Что заказать</h2><label for="shop">Ресторан</label><select id="shop">' + options(Object.keys(catalog.shops),draft.shop) + '</select><p class="sub">' + shop.address + '</p>' +
    Object.entries(shop.menu).map(([name,price]) => '<div class="row"><div><b>'+name+'</b><br><small>'+price+' ₽</small></div><input aria-label="Количество: '+name+'" class="qty" type="number" min="0" max="20" data-item="'+name+'" value="'+Number(draft.items[name] || 0)+'"></div>').join('') +
    '</div><div class="card"><h2>Куда доставить</h2><label for="address">Адрес в районе</label><select id="address">'+options(catalog.addresses,draft.address)+'</select><label for="comment">Комментарий курьеру</label><textarea id="comment" rows="3" maxlength="300" placeholder="Например, подъезд и этаж">'+escapeHtml(draft.comment || '')+'</textarea><div class="split"><strong>Итого</strong><strong id="total"></strong></div><button class="wide" id="submit">Оформить заказ</button></div></form><section id="list"></section>';
  $('shop').onchange = e => {draft.shop=e.target.value;draft.items={};delete draft.token;save();client();renderOrders();};
  const update = () => {
    $('total').textContent = Object.entries(draft.items).reduce((sum,[n,q]) => sum + shop.menu[n]*q,0) + ' ₽';
    $('submit').disabled = busy || !Object.values(draft.items).some(q=>q>0);
  };
  $('form').oninput = e => {
    if(e.target.id === 'shop') return;
    if(e.target.dataset.item) draft.items[e.target.dataset.item] = Number(e.target.value);
    draft.address=$('address').value;draft.comment=$('comment').value;delete draft.token;save();update();
  };
  $('form').onsubmit = async e => {
    e.preventDefault(); if(busy) return;
    busy=true;update();
    const fields = [...e.target.elements]; fields.forEach(el=>el.disabled=true);
    draft.token ||= crypto.randomUUID();save();
    try {
      const result = await api('orders',{...draft,comment:draft.comment || '',items:Object.fromEntries(Object.entries(draft.items).filter(([,q])=>q>0))});
      $('message').textContent='Заказ №'+result.id+' оформлен.';
      draft={};save();client(); await refreshOrders();
    } catch(err) {$('message').textContent=err.status === 401 ? err.message : 'Не удалось подтвердить заказ. Данные сохранены. Повторите отправку.';}
    finally {busy=false;fields.forEach(el=>el.disabled=false); if($('submit')) $('submit').disabled=!Object.values(draft.items).some(q=>q>0);}
  };
  update();
}
function card(o, active) {
  const lines=Object.entries(o.items).map(([n,q])=>escapeHtml(n)+' × '+q).join(', ');
  return '<article class="card"><div class="split"><h2>Заказ №'+o.id+'</h2><span class="badge">'+stages[o.stage]+'</span></div><p><b>'+escapeHtml(o.shop)+'</b><br>'+lines+' · '+o.total+' ₽</p><p><small>Забрать</small><br>'+escapeHtml(o.pickup)+'</p><p><small>Доставить</small><br>'+escapeHtml(o.address)+'</p>'+(o.comment?'<p><small>Комментарий</small><br>'+escapeHtml(o.comment)+'</p>':'')+
    (courier && o.stage<3?'<button data-order="'+o.id+'" data-stage="'+o.stage+'" '+(!online || busy || (active && o.stage===0)?'disabled':'')+'>'+actions[o.stage]+'</button>':'')+'</article>';
}
function renderOrders() {
  const visible = orders.slice();
  const active=orders.find(o=>o.stage===1 || o.stage===2);
  visible.sort((a,b)=>Number(b===active)-Number(a===active) || Number(a.stage===3)-Number(b.stage===3));
  $('list').innerHTML=(courier?'':'<h2>Мои заказы</h2>')+(visible.map(o=>card(o,active)).join('') || '<div class="card empty">'+(online?(courier?'Ожидаем первый заказ':'Здесь появится оформленный заказ'):'Ожидаем данные сервиса заказов')+'</div>');
}
async function refreshOrders() {
  const id=++generation;
  try {
    const fresh=await api('orders');if(id!==generation)return;
    orders=fresh;online=true;$('ordersWarn').textContent='';
  } catch(err) {
    if(id!==generation)return;
    online=false;$('ordersWarn').textContent=err.status===401 ? err.message : 'Сервис заказов недоступен. '+(orders.length?'Показаны последние полученные данные.':'Ожидаем подключения.');
  }
  renderOrders();
}
let map, markerLayer, routeLine, displayedKey, revision = 0;
function initMap() {
  if (!window.L) {
    $('tileStatus').textContent='Не удалось открыть карту. Адреса доступны в карточке.';
    return;
  }
  map=L.map('map').setView(catalog.places[catalog.base],15);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
  }).on('tileerror',()=>{$('tileStatus').textContent='Часть карты не загрузилась. Проверьте подключение к интернету.';})
    .on('tileload',()=>{$('tileStatus').textContent='';}).addTo(map);
  markerLayer=L.layerGroup().addTo(map);
}
function clearLine() {
  if (routeLine) { routeLine.remove(); routeLine=null; }
}
function showStops(key, stops) {
  if (key===displayedKey) return;
  displayedKey=key;
  clearLine();
  if (!map) return;
  markerLayer.clearLayers();
  const coords=[];
  for (const [address,label,color] of stops) {
    const coord=catalog.places[address];
    if (!coord) continue;
    coords.push(coord);
    L.circleMarker(coord,{radius:8,color:'#fff',weight:2,fillColor:color,fillOpacity:1})
      .bindTooltip(label+' · '+address).addTo(markerLayer);
  }
  if (coords.length) map.fitBounds(coords,{padding:[35,35],maxZoom:17});
}
async function navigation() {
  const current=++revision;
  const active=orders.find(o=>o.stage===1 || o.stage===2);
  const previous=orders.filter(o=>o.stage===3).sort((a,b)=>b.finished-a.finished)[0];
  const lastStop=catalog.places[previous?.address]?previous.address:catalog.base;
  const pickup=active?.stage===1;
  const start=pickup?lastStop:active?.pickup;
  const end=pickup?active?.pickup:active?.address;
  const key=active?[active.id,active.stage,start,end].join('|'):'idle';
  const routeChanged=displayedKey!==key;
  const stops=active?[[start,'Откуда','#226b51'],[end,'Куда','#a14825']]:
    Object.keys(catalog.places).map(address=>[address,'Точка района','#226b51']);
  showStops(key,stops);
  $('routeTitle').textContent=active?(pickup?'До ресторана':'До клиента'):'Тверской район';
  $('leg').textContent=active?start+' → '+end:'Примите заказ, чтобы увидеть пеший маршрут.';
  if (routeChanged) $('distance').textContent='';
  try {
    const route=active?await api('route',{start,end}):await api('health');
    if(current!==revision) return;
    if(active){
      if(map && !routeLine && route.points.length>1){
        routeLine=L.polyline(route.points,{color:'#25614b',weight:5}).addTo(map);
        map.fitBounds(routeLine.getBounds(),{padding:[32,32],maxZoom:17});
      }
      $('distance').textContent=route.meters?'Пешком · '+route.meters+' м':'Вы на месте';
    }
    $('navWarn').textContent='';
  } catch(err) {
    if(current!==revision) return;
    clearLine();$('distance').textContent='';
    $('navWarn').textContent=err.message==='Связь с сервисом прервана'?'Навигация временно недоступна. Адреса указаны в карточке заказа.':err.message;
  }
}
async function start() {
  $('roleLabel').textContent=courier?'Курьерская служба':'Клиент';
  $('title').textContent=courier?'Окно курьера':'Оформить заказ';
  $('ordersWarn').className=$('navWarn').className='warn';
  catalog=await api('catalog');
  if(courier){
    $('content').innerHTML='<div class="grid"><section id="list"></section><aside class="card" id="route"><h2 id="routeTitle">Тверской район</h2><p id="leg"></p><div id="map" aria-label="Карта района доставки"></div><small id="tileStatus"></small><strong id="distance"></strong></aside></div>';
    initMap();
    $('list').onclick=async e=>{
      const b=e.target.closest('button[data-order]');if(!b || busy)return;
      busy=true;renderOrders();
      try {await api('orders/'+b.dataset.order+'/advance',{stage:Number(b.dataset.stage)});$('message').textContent='';}
      catch(err){$('message').textContent=err.message;}
      finally {busy=false;await refreshOrders();await navigation();}
    };
  } else client();
  async function poll(fn) {try{await fn();}finally{setTimeout(()=>poll(fn),1800);}}
  poll(refreshOrders);if(courier)poll(navigation);
}
start().catch(()=>{$('message').textContent='Не удалось загрузить страницу. Обновите её.';});
