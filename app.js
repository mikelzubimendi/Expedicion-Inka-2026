'use strict';

const DATA_URL = 'localidades.geojson';
const STREAM_URL = 'https://www.youtube.com/watch?v=CtAJIkQDiyQ';
const THEME_KEY = 'mapa-inka-theme';

const ui = {
  panel: document.getElementById('panel'),
  toggle: document.getElementById('toggle'),
  search: document.getElementById('search'),
  clear: document.getElementById('clear'),
  days: document.getElementById('days'),
  list: document.getElementById('list'),
  count: document.getElementById('count'),
  empty: document.getElementById('empty'),
  reset: document.getElementById('reset'),
};

/* ---------------------------------------------------------------------------
 * Tema claro / oscuro
 * ------------------------------------------------------------------------- */

const SUN_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>';

function storedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch (error) {
    return null;
  }
}

function updateThemeButtons(theme) {
  const isLight = theme === 'light';
  document.querySelectorAll('.theme-button').forEach((button) => {
    button.innerHTML = isLight ? MOON_ICON : SUN_ICON;
    button.setAttribute('aria-label', isLight ? 'Cambiar a modo oscuro' : 'Cambiar a modo claro');
    button.setAttribute('title', isLight ? 'Modo oscuro' : 'Modo claro');
    button.setAttribute('aria-pressed', String(isLight));
  });
}

function applyTheme(theme, persist) {
  const next = theme === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  if (persist) {
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (error) {
      /* sin almacenamiento disponible */
    }
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', next === 'light' ? '#f4efe6' : '#08080c');
  updateThemeButtons(next);
}

applyTheme(storedTheme() || 'dark', false);

/* ---------------------------------------------------------------------------
 * Mapa base
 * ------------------------------------------------------------------------- */

const map = L.map('map', {
  zoomControl: false,
  minZoom: 1,
  maxZoom: 18,
  worldCopyJump: true,
}).setView([-38.4, -63.6], 4);

L.control.zoom({ position: 'bottomright' }).addTo(map);
L.control.scale({ position: 'bottomleft', imperial: false }).addTo(map);

const darkBase = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  className: 'dark-tiles',
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
});

const satellite = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {
    maxZoom: 18,
    attribution: 'Imágenes &copy; <a href="https://www.esri.com" target="_blank" rel="noopener">Esri</a>, Maxar, Earthstar Geographics',
  }
);

darkBase.addTo(map);
L.control.layers({ 'Noche': darkBase, 'Satélite': satellite }, null, {
  position: 'topright',
  collapsed: true,
}).addTo(map);

const ThemeToggle = L.Control.extend({
  options: { position: 'topright' },
  onAdd() {
    const container = L.DomUtil.create('div', 'leaflet-bar theme-control');
    const button = L.DomUtil.create('button', 'theme-button', container);
    button.type = 'button';
    updateThemeButtons(document.documentElement.dataset.theme);
    button.addEventListener('click', () => {
      applyTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light', true);
    });
    L.DomEvent.disableClickPropagation(container);
    L.DomEvent.disableScrollPropagation(container);
    return container;
  },
});

new ThemeToggle().addTo(map);
updateThemeButtons(document.documentElement.dataset.theme);

/* ---------------------------------------------------------------------------
 * Capa de marcadores
 * ------------------------------------------------------------------------- */

const canCluster = typeof L.markerClusterGroup === 'function';

const markers = canCluster
  ? L.markerClusterGroup({
      showCoverageOnHover: false,
      spiderfyOnMaxZoom: true,
      maxClusterRadius: 48,
      iconCreateFunction(cluster) {
        const count = cluster.getChildCount();
        const size = count < 10 ? 34 : count < 50 ? 40 : 46;
        return L.divIcon({
          html: '<span>' + count + '</span>',
          className: 'cluster',
          iconSize: L.point(size, size),
        });
      },
    })
  : L.layerGroup();

markers.addTo(map);

/* ---------------------------------------------------------------------------
 * Utilidades
 * ------------------------------------------------------------------------- */

function normalize(text) {
  return String(text)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
}

function formatCoords(lat, lng) {
  return lat.toFixed(4) + ', ' + lng.toFixed(4);
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function matchesSearch(key, query) {
  const tokens = normalize(query).split(/\s+/).filter(Boolean);
  return tokens.every((token) => {
    const pattern = new RegExp('(^|[\\s@.,;:()\\-])' + escapeRegExp(token));
    return pattern.test(key);
  });
}

function searchScore(place, query) {
  const needle = normalize(query);
  const bareNeedle = needle.replace(/^@/, '');
  const name = normalize(place.name);
  if (name === needle) return 0;
  if (name.startsWith(needle)) return 1;
  if (name.split(/\s+/).some((word) => word.startsWith(needle))) return 2;
  if (normalize(place.province).startsWith(needle)) return 3;
  if (normalize(place.country).startsWith(needle)) return 4;
  if (place.people.some((person) => normalize(person.usuario).replace(/^@/, '').startsWith(bareNeedle))) return 5;
  return 6;
}

function mapPadding() {
  const desktop = window.matchMedia('(min-width: 900px)').matches;
  const panel = ui.panel.getBoundingClientRect();

  if (desktop) {
    return {
      paddingTopLeft: L.point(Math.min(panel.width + 40, window.innerWidth * 0.5), 24),
      paddingBottomRight: L.point(24, 24),
    };
  }

  const panelHeight = ui.panel.classList.contains('is-collapsed')
    ? panel.height
    : Math.min(panel.height, window.innerHeight * 0.55);

  return {
    paddingTopLeft: L.point(16, 16),
    paddingBottomRight: L.point(16, panelHeight + 20),
  };
}

function popupPadding() {
  const desktop = window.matchMedia('(min-width: 900px)').matches;
  if (desktop) {
    return {
      topLeft: L.point(24, 24),
      bottomRight: L.point(24, 24),
    };
  }
  const sheet = ui.panel.getBoundingClientRect().height;
  return {
    topLeft: L.point(16, 70),
    bottomRight: L.point(16, sheet + 24),
  };
}

function updatePopupPaddings() {
  const padding = popupPadding();
  for (const place of places) {
    const popup = place.marker && place.marker.getPopup();
    if (!popup) continue;
    popup.options.autoPanPaddingTopLeft = padding.topLeft;
    popup.options.autoPanPaddingBottomRight = padding.bottomRight;
  }
}

const HOME_BOUNDS = L.latLngBounds([-56.5, -76], [-20, -50]);

function homePlaces() {
  const inside = places.filter((place) => HOME_BOUNDS.contains([place.lat, place.lng]));
  return inside.length >= places.length * 0.8 ? inside : places;
}

function fitPlaces(target, animate) {
  if (!target.length) return;
  const bounds = L.latLngBounds(target.map((place) => [place.lat, place.lng]));
  const options = Object.assign({ maxZoom: 10 }, mapPadding());
  if (animate) {
    map.flyToBounds(bounds, Object.assign({ duration: 0.9 }, options));
  } else {
    map.fitBounds(bounds, options);
  }
}

function fitHomePlaces(animate) {
  fitPlaces(homePlaces(), animate);
}

function fitAllPlaces(animate) {
  const visible = places.filter((place) => place.onMap);
  fitPlaces(visible.length ? visible : places, animate);
}

function zoomForPlace(place) {
  if (place.tipo === 'pais') return 4;
  if (place.tipo === 'provincia' || place.tipo === 'region') return 5;
  return 12;
}

/* ---------------------------------------------------------------------------
 * Estado
 * ------------------------------------------------------------------------- */

let places = [];
let activePlace = null;
let totalPeople = 0;
let activeDay = '';

function personHasDay(person, day) {
  if (!day) return true;
  if (Array.isArray(person.dias) && person.dias.length) return person.dias.includes(day);
  if (person.dia) return person.dia === day;
  // Datos antiguos sin día: se muestran en todos los filtros.
  return true;
}

function placePeople(place) {
  return place.people.filter((person) => personHasDay(person, activeDay));
}

function placeKeyForDay(place, day) {
  if (!day) return place.key;
  const parts = [place.name, place.province, place.country];
  for (const person of place.people) {
    if (!personHasDay(person, day)) continue;
    parts.push(person.usuario);
    const comments = person.comentariosPorDia && person.comentariosPorDia[day];
    if (comments && comments.length) {
      parts.push(...comments);
    } else {
      parts.push(person.mensaje, ...person.comentarios);
    }
  }
  return normalize(parts.join(' '));
}

function personComments(person) {
  if (activeDay && person.comentariosPorDia && person.comentariosPorDia[activeDay]) {
    return person.comentariosPorDia[activeDay];
  }
  return person.mensaje ? [person.mensaje, ...person.comentarios] : person.comentarios;
}

/* ---------------------------------------------------------------------------
 * Datos de oyentes
 * ------------------------------------------------------------------------- */

function normalizePerson(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const usuario = typeof raw.Usuario === 'string' ? raw.Usuario.trim() : '';
  const mensaje = typeof raw.Mensaje === 'string' ? raw.Mensaje.trim() : '';
  const comentarios = Array.isArray(raw.Comentarios)
    ? raw.Comentarios.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim())
    : [];
  const dia = typeof raw.Dia === 'string' ? raw.Dia.trim() : '';
  const dias = Array.isArray(raw.Dias)
    ? raw.Dias.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim())
    : [];
  const comentariosPorDia = {};
  if (raw.ComentariosPorDia && typeof raw.ComentariosPorDia === 'object') {
    for (const [key, value] of Object.entries(raw.ComentariosPorDia)) {
      if (!Array.isArray(value)) continue;
      const items = value
        .filter((item) => typeof item === 'string' && item.trim())
        .map((item) => item.trim());
      if (items.length) comentariosPorDia[key] = items;
    }
  }
  if (!usuario && !mensaje && comentarios.length === 0) return null;
  return { usuario, mensaje, comentarios, dia, dias, comentariosPorDia };
}

function readPeople(properties) {
  if (Array.isArray(properties.Oyentes)) {
    return properties.Oyentes.map(normalizePerson).filter(Boolean);
  }

  // Compatibilidad con el formato anterior (un usuario por feature).
  const legacy = [];
  if (properties.Usuario || properties.Comentario) {
    legacy.push({
      usuario: typeof properties.Usuario === 'string' ? properties.Usuario : '',
      mensaje: typeof properties.Comentario === 'string' ? properties.Comentario : '',
      comentarios: [],
      dia: '',
      dias: [],
      comentariosPorDia: {},
    });
  }
  return legacy;
}

/* ---------------------------------------------------------------------------
 * Popups y filas de la lista
 * ------------------------------------------------------------------------- */

function buildPopup(place) {
  const root = document.createElement('div');
  root.className = 'popup';
  const peopleList = placePeople(place);

  const title = document.createElement('h2');
  title.className = 'popup__title';
  title.textContent = place.name;

  const subtitleParts = [];
  if (place.tipo === 'pais') {
    subtitleParts.push('País');
  } else if (place.tipo === 'provincia') {
    subtitleParts.push('Provincia');
    if (place.country) subtitleParts.push(place.country);
  } else {
    if (place.province && normalize(place.province) !== normalize(place.name)) subtitleParts.push(place.province);
    if (place.country && normalize(place.country) !== normalize(place.name)) subtitleParts.push(place.country);
  }

  const subtitle = document.createElement('p');
  subtitle.className = 'popup__subtitle';
  subtitle.textContent = subtitleParts.join(', ') || 'Argentina';

  const meta = document.createElement('p');
  meta.className = 'popup__meta';
  if (peopleList.length === 0) {
    meta.textContent = activeDay ? 'Sin oyentes ese día' : 'Sin oyentes registrados';
  } else {
    meta.textContent = peopleList.length + (peopleList.length === 1 ? ' oyente del stream' : ' oyentes del stream') +
      (activeDay ? ' · ' + activeDay : '');
  }

  const people = document.createElement('div');
  people.className = 'popup__people';
  for (const person of peopleList) {
    const block = document.createElement('div');
    block.className = 'person';

    const user = document.createElement('p');
    user.className = 'person__user';
    user.textContent = person.usuario || 'Anónimo';
    block.appendChild(user);

    if (activeDay) {
      for (const comment of personComments(person)) {
        const paragraph = document.createElement('p');
        paragraph.className = 'person__comment';
        paragraph.textContent = comment;
        block.appendChild(paragraph);
      }
    } else {
      const dayKeys = (person.dias && person.dias.length)
        ? person.dias
        : Object.keys(person.comentariosPorDia || {});
      const grouped = dayKeys.length > 1 && Object.keys(person.comentariosPorDia || {}).length > 0;

      if (grouped) {
        for (const day of dayKeys) {
          const comments = person.comentariosPorDia[day] || [];
          if (!comments.length) continue;
          const heading = document.createElement('p');
          heading.className = 'person__day';
          heading.textContent = day;
          block.appendChild(heading);
          for (const comment of comments) {
            const paragraph = document.createElement('p');
            paragraph.className = 'person__comment';
            paragraph.textContent = comment;
            block.appendChild(paragraph);
          }
        }
      } else {
        if (person.mensaje) {
          const message = document.createElement('p');
          message.className = 'person__message';
          message.textContent = person.mensaje;
          block.appendChild(message);
        }

        for (const comment of person.comentarios) {
          const paragraph = document.createElement('p');
          paragraph.className = 'person__comment';
          paragraph.textContent = comment;
          block.appendChild(paragraph);
        }
      }
    }

    people.appendChild(block);
  }

  const coords = document.createElement('p');
  coords.className = 'popup__coords';
  coords.textContent = formatCoords(place.lat, place.lng);

  const links = document.createElement('p');
  links.className = 'popup__links';

  const google = document.createElement('a');
  google.href = 'https://www.google.com/maps/search/?api=1&query=' + place.lat + ',' + place.lng;
  google.target = '_blank';
  google.rel = 'noopener';
  google.textContent = 'Google Maps';

  const osmLink = document.createElement('a');
  osmLink.href = 'https://www.openstreetmap.org/?mlat=' + place.lat + '&mlon=' + place.lng +
    '#map=12/' + place.lat + '/' + place.lng;
  osmLink.target = '_blank';
  osmLink.rel = 'noopener';
  osmLink.textContent = 'OpenStreetMap';

  links.append(google, document.createTextNode(' · '), osmLink);

  root.append(title, subtitle, meta);
  if (peopleList.length) root.appendChild(people);
  root.append(coords, links);
  return root;
}

function peopleSummary(place) {
  const peopleList = placePeople(place);
  if (!peopleList.length) return activeDay ? 'Sin oyentes ese día' : 'Sin oyentes';
  if (peopleList.length <= 2) {
    return peopleList.map((person) => person.usuario || 'Anónimo').join(', ');
  }
  return peopleList.length + ' oyentes';
}

function createRow(place) {
  const item = document.createElement('li');

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'place';
  button.title = place.name;

  const dot = document.createElement('span');
  dot.className = 'place__dot';
  dot.setAttribute('aria-hidden', 'true');

  const body = document.createElement('span');
  body.className = 'place__body';

  const name = document.createElement('span');
  name.className = 'place__name';
  name.textContent = place.name;

  const meta = document.createElement('span');
  meta.className = 'place__meta';
  const metaParts = [];
  if (place.tipo === 'pais') {
    metaParts.push('País');
  } else if (place.tipo === 'provincia') {
    metaParts.push('Provincia');
  } else if (place.province && normalize(place.province) !== normalize(place.name)) {
    metaParts.push(place.province);
  } else if (place.country && normalize(place.country) !== normalize(place.name)) {
    metaParts.push(place.country);
  }
  metaParts.push(peopleSummary(place));
  meta.textContent = metaParts.join(' · ');
  place.metaParts = metaParts.slice(0, -1);
  place.metaEl = meta;

  body.append(name, meta);
  button.append(dot, body);

  button.addEventListener('click', () => {
    setActive(place);
    focusPlace(place);
  });

  button.addEventListener('mouseenter', () => highlight(place, true));
  button.addEventListener('mouseleave', () => highlight(place, false));
  button.addEventListener('focus', () => highlight(place, true));
  button.addEventListener('blur', () => highlight(place, false));

  item.appendChild(button);
  place.row = item;
  place.button = button;
  return item;
}

function updateRow(place) {
  if (!place.metaEl) return;
  const parts = (place.metaParts || []).concat(peopleSummary(place));
  place.metaEl.textContent = parts.join(' · ');
}

/* ---------------------------------------------------------------------------
 * Interacciones
 * ------------------------------------------------------------------------- */

function highlight(place, on) {
  place.button.classList.toggle('is-hover', on);
  if (!place.onMap) return;
  place.marker.setStyle({ weight: on ? 3 : 1.5 });
  place.marker.setRadius(on ? 9 : 6);
}

function setActive(place) {
  if (activePlace && activePlace !== place) {
    activePlace.button.classList.remove('is-active');
  }
  activePlace = place;
  place.button.classList.add('is-active');
  place.row.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

let pendingPopup = null;

function collapsePanelOnMobile() {
  if (window.matchMedia('(min-width: 900px)').matches) return;
  if (ui.panel.classList.contains('is-collapsed')) return;
  ui.panel.classList.add('is-collapsed');
  ui.toggle.setAttribute('aria-expanded', 'false');
  ui.toggle.setAttribute('aria-label', 'Mostrar la lista de localidades');
  updatePopupPaddings();
  updateSheetOffset();
}

function focusPlace(place) {
  collapsePanelOnMobile();
  if (pendingPopup) {
    map.off('moveend', pendingPopup);
    pendingPopup = null;
  }

  const zoom = Math.max(map.getZoom(), zoomForPlace(place));
  const target = [place.lat, place.lng];
  let center = L.latLng(target);

  if (!window.matchMedia('(min-width: 900px)').matches) {
    // En celular el panel tapa la mitad inferior: centramos el punto un poco
    // más arriba para que el popup no quede debajo de la hoja.
    const sheet = ui.panel.getBoundingClientRect().height;
    center = map.unproject(map.project(target, zoom).add([0, sheet / 2]), zoom);
  }

  const openPopup = () => {
    pendingPopup = null;
    place.marker.openPopup();
  };

  const openWhenReady = () => {
    const current = map.getCenter();
    const sameCenter = Math.abs(current.lat - center.lat) < 0.000001 &&
      Math.abs(current.lng - center.lng) < 0.000001;
    if (sameCenter && map.getZoom() === zoom) {
      openPopup();
      return;
    }
    // Abrimos el popup cuando termina el movimiento para que Leaflet calcule
    // bien el auto-pan, sobre todo con listas largas de oyentes.
    pendingPopup = openPopup;
    map.once('moveend', openPopup);
    map.flyTo(center, zoom, { duration: 0.7 });
  };

  if (typeof markers.zoomToShowLayer === 'function') {
    markers.zoomToShowLayer(place.marker, openWhenReady);
  } else {
    openWhenReady();
  }
}

function applyFilter(query) {
  const needle = normalize(query);
  let visible = 0;
  let visiblePeople = 0;

  for (const place of places) {
    const dayMatches = !activeDay || placePeople(place).length > 0;
    const searchKey = activeDay ? placeKeyForDay(place, activeDay) : place.key;
    const matches = dayMatches && (needle === '' || matchesSearch(searchKey, query));
    place.row.hidden = !matches;
    place.score = (matches && needle !== '') ? searchScore(place, query) : 0;
    updateRow(place);

    if (matches) {
      if (!place.onMap) {
        markers.addLayer(place.marker);
        place.onMap = true;
      }
      visible += 1;
      visiblePeople += placePeople(place).length;
    } else if (place.onMap) {
      markers.removeLayer(place.marker);
      place.onMap = false;
      if (activePlace === place) {
        place.button.classList.remove('is-active');
        activePlace = null;
      }
    }
  }

  if (needle === '' && !activeDay) {
    ui.count.textContent = places.length + ' lugares · ' + totalPeople + ' oyentes';
  } else if (needle === '') {
    ui.count.textContent = visible + ' lugares · ' + visiblePeople + ' oyentes · ' + activeDay;
  } else {
    ui.count.textContent = visible + ' de ' + places.length + ' lugares';
  }

  const ordered = places.slice().sort((a, b) => {
    if (a.row.hidden !== b.row.hidden) return a.row.hidden ? 1 : -1;
    return (a.score - b.score) || a.name.localeCompare(b.name, 'es');
  });
  for (const place of ordered) ui.list.appendChild(place.row);

  ui.empty.hidden = visible !== 0;
  ui.clear.hidden = needle === '';
}

function clearFilter() {
  ui.search.value = '';
  applyFilter('');
}

function setDay(day) {
  activeDay = day;
  ui.days.querySelectorAll('.day').forEach((button) => {
    const on = button.dataset.day === day;
    button.classList.toggle('is-active', on);
    button.setAttribute('aria-pressed', String(on));
  });
  applyFilter(ui.search.value);
  if (activePlace && activePlace.onMap) {
    activePlace.marker.closePopup();
    activePlace.marker.openPopup();
  }
}

function collectDays() {
  const seen = new Set();
  for (const place of places) {
    for (const person of place.people) {
      for (const day of (person.dias && person.dias.length ? person.dias : [person.dia])) {
        if (day) seen.add(day);
      }
    }
  }
  return Array.from(seen).sort((a, b) => {
    const na = Number((a.match(/\d+/) || [99])[0]);
    const nb = Number((b.match(/\d+/) || [99])[0]);
    return na - nb || a.localeCompare(b, 'es');
  });
}

function buildDayFilter(days, videos) {
  const titles = {};
  for (const video of videos || []) {
    if (video && video.dia && video.titulo) titles[video.dia] = video.titulo;
  }

  ui.days.textContent = '';
  for (const day of [''].concat(days)) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'day';
    button.dataset.day = day;
    button.textContent = day || 'Todos';
    if (day && titles[day]) {
      button.title = titles[day];
      button.setAttribute('aria-label', 'Filtrar por ' + titles[day]);
    }
    const on = day === activeDay;
    button.classList.toggle('is-active', on);
    button.setAttribute('aria-pressed', String(on));
    button.addEventListener('click', () => setDay(day));
    ui.days.appendChild(button);
  }
}

// Mantiene los controles de Leaflet por encima de la hoja inferior en celulares.
function updateSheetOffset() {
  document.documentElement.style.setProperty('--sheet-offset', ui.panel.offsetHeight + 16 + 'px');
}

if ('ResizeObserver' in window) {
  new ResizeObserver(updateSheetOffset).observe(ui.panel);
}
window.addEventListener('resize', updateSheetOffset);
updateSheetOffset();

/* ---------------------------------------------------------------------------
 * Carga de datos
 * ------------------------------------------------------------------------- */

function showError(message) {
  ui.count.textContent = 'No se pudieron cargar los datos';
  ui.empty.hidden = false;
  ui.empty.textContent = message;
  ui.list.hidden = true;
}

function init(data) {
  const features = Array.isArray(data.features) ? data.features : [];

  const points = features.filter((feature) => {
    return feature &&
      feature.geometry &&
      feature.geometry.type === 'Point' &&
      Array.isArray(feature.geometry.coordinates) &&
      feature.geometry.coordinates.length >= 2;
  });

  if (!points.length) {
    showError('El archivo localidades.geojson no contiene puntos para mostrar.');
    return;
  }

  const fragment = document.createDocumentFragment();

  places = points
    .map((feature) => {
      const lng = Number(feature.geometry.coordinates[0]);
      const lat = Number(feature.geometry.coordinates[1]);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;

      const properties = feature.properties || {};
      const name = String(
        properties.Lugar || properties.Nombre || properties.name || 'Lugar sin nombre'
      ).trim();
      const province = String(properties.Provincia || properties.provincia || '').trim();
      const country = String(properties.Pais || properties.pais || 'Argentina').trim();
      const tipo = String(properties.Tipo || properties.tipo || 'localidad').trim();
      const people = readPeople(properties);

      const key = normalize([
        name,
        province,
        country,
        ...people.flatMap((person) => [
          person.usuario,
          person.mensaje,
          ...person.comentarios,
        ]),
      ].join(' '));

      return { name, province, country, tipo, people, lat, lng, key, onMap: false };
    })
    .filter(Boolean)
    .sort((a, b) => a.name.localeCompare(b.name, 'es'));

  totalPeople = places.reduce((total, place) => total + place.people.length, 0);

  const metadata = data.metadata && typeof data.metadata === 'object' ? data.metadata : {};
  const days = Array.isArray(metadata.dias) && metadata.dias.length ? metadata.dias : collectDays();
  buildDayFilter(days, metadata.videos);

  for (const place of places) {
    place.marker = L.circleMarker([place.lat, place.lng], {
      className: 'dot',
      radius: 6,
      color: '#ffc7b8',
      weight: 1.5,
      fillColor: '#ff4d2e',
      fillOpacity: 0.95,
    });

    const padding = popupPadding();
    place.marker.bindPopup(() => buildPopup(place), {
      closeButton: true,
      maxWidth: 330,
      autoPanPaddingTopLeft: padding.topLeft,
      autoPanPaddingBottomRight: padding.bottomRight,
    });

    place.marker.on('click', () => {
      setActive(place);
      collapsePanelOnMobile();
    });
    place.marker.on('mouseover', () => highlight(place, true));
    place.marker.on('mouseout', () => highlight(place, false));

    markers.addLayer(place.marker);
    place.onMap = true;

    fragment.appendChild(createRow(place));
  }

  ui.list.appendChild(fragment);
  ui.count.textContent = places.length + ' lugares · ' + totalPeople + ' oyentes';
  updatePopupPaddings();
  fitHomePlaces(false);
}

/* ---------------------------------------------------------------------------
 * Eventos de la interfaz
 * ------------------------------------------------------------------------- */

ui.search.addEventListener('input', (event) => applyFilter(event.target.value));

ui.search.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    const first = places.find((place) => !place.row.hidden);
    if (first) {
      setActive(first);
      focusPlace(first);
    }
  } else if (event.key === 'Escape') {
    clearFilter();
  }
});

ui.clear.addEventListener('click', () => {
  clearFilter();
  ui.search.focus();
});

ui.reset.addEventListener('click', () => {
  clearFilter();
  fitAllPlaces(true);
});

ui.toggle.addEventListener('click', () => {
  const collapsed = ui.panel.classList.toggle('is-collapsed');
  ui.toggle.setAttribute('aria-expanded', String(!collapsed));
  ui.toggle.setAttribute('aria-label', collapsed ? 'Mostrar la lista de localidades' : 'Ocultar la lista de localidades');
  updatePopupPaddings();
});

/* ---------------------------------------------------------------------------
 * Arranque
 * ------------------------------------------------------------------------- */

if (location.protocol === 'file:') {
  showError('Abrí el sitio desde un servidor local (por ejemplo: python3 -m http.server) o publicalo en GitHub Pages.');
} else {
  fetch(DATA_URL)
    .then((response) => {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    })
    .then(init)
    .catch(() => {
      showError('No se pudo leer localidades.geojson. Verificá que el archivo esté junto a index.html.');
    });
}
