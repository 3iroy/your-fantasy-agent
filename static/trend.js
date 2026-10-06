// Charts use actual tool results; all rolling windows end at the selected game.
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const colors = {game: '#8998b0', four: '#70dac7', ten: '#bdabff', baseline: '#f9ae6b'};
  function svgNode(tag, attrs = {}, text) {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function rolling(games, size) {
    return games.map((_, index) => index < size - 1 ? null :
      games.slice(index - size + 1, index + 1).reduce((total, game) => total + game.fantasy_points, 0) / size);
  }
  function format(value) { return value === null ? '—' : value.toFixed(1); }
  window.createFantasyTrend = function (result) {
    const games = result.game_history;
    if (!result.ok || !Array.isArray(games) || games.length < 10 || games.some(game =>
      !Number.isFinite(game.fantasy_points) || !/^\d{4}-\d{2}-\d{2}$/.test(game.date)
      || !Number.isFinite(Date.parse(game.date)) || game.date > result.as_of_date)) return null;
    const baseline = result.baseline_before_last_10?.fantasy_points_per_game;
    if (!Number.isFinite(baseline)) return null;
    const four = rolling(games, 4), ten = rolling(games, 10);
    const dates = games.map(game => Date.parse(`${game.date}T00:00:00Z`));
    const width = 800, height = 310;
    const pad = {left: 50, right: 18, top: 22, bottom: 42};
    const plotWidth = width - pad.left - pad.right, plotHeight = height - pad.top - pad.bottom;
    const scores = [baseline, ...games.map(game => game.fantasy_points)];
    const low = Math.floor((Math.min(0, ...scores) - 3) / 10) * 10;
    const high = Math.ceil((Math.max(...scores) + 3) / 10) * 10;
    const x = index => pad.left + (dates[index] - dates[0]) / Math.max(1, dates.at(-1) - dates[0]) * plotWidth;
    const y = score => pad.top + (high - score) / Math.max(1, high - low) * plotHeight;
    const figure = document.createElement('figure');
    figure.className = 'fantasy-trend';
    const caption = document.createElement('figcaption');
    caption.textContent = `${result.player.name} · Fantasy points trend`;
    const subtitle = document.createElement('p');
    subtitle.className = 'trend-subtitle';
    subtitle.textContent = `${result.season_label} · Through ${result.as_of_date} · ${games.length} played games · Your scoring rules`;
    const legend = document.createElement('div');
    legend.className = 'trend-legend';
    for (const [label, color] of [['Per game', colors.game], ['4-game average', colors.four], ['10-game average', colors.ten], ['Earlier baseline', colors.baseline]]) {
      const item = document.createElement('span');
      const swatch = document.createElement('i');
      swatch.style.backgroundColor = color;
      item.append(swatch, document.createTextNode(label));
      legend.append(item);
    }
    const svg = svgNode('svg', {viewBox: `0 0 ${width} ${height}`, tabindex: 0, role: 'img',
      'aria-label': `${result.player.name} fantasy points per game, four-game and ten-game averages. Focus and use left and right arrows to inspect games.`});
    svg.append(svgNode('title', {}, 'Historical fantasy points and trailing averages'),
      svgNode('desc', {}, `Actual played games through ${result.as_of_date}. Orange dashed line is the earlier baseline. The shaded area contains the last ten appearances. Four games are not necessarily a calendar week.`));
    const shadeStart = (x(games.length - 11) + x(games.length - 10)) / 2;
    svg.append(svgNode('rect', {x: shadeStart, y: pad.top, width: width-pad.right-shadeStart, height: plotHeight, fill: '#bdabff', opacity: 0.055}));
    for (let index = 0; index <= 4; index++) {
      const score = low + (high - low) * index / 4;
      svg.append(svgNode('line', {x1: pad.left, x2: width-pad.right, y1: y(score), y2: y(score), stroke: '#344155', 'stroke-width': 1}),
        svgNode('text', {x: pad.left-9, y: y(score)+4, 'text-anchor': 'end', fill: '#a9b4c7', 'font-size': 14}, score.toFixed(0)));
    }
    svg.append(svgNode('text', {x: pad.left, y: 12, fill: '#a9b4c7', 'font-size': 10, class: 'trend-axis-title'}, 'FP / GAME'));
    for (let index = 0; index <= 3; index++) {
      const day = dates[0] + (dates.at(-1) - dates[0]) * index / 3;
      const label = new Date(day).toISOString().slice(5, 10);
      svg.append(svgNode('text', {x: pad.left+plotWidth*index/3, y: height-15,
        'text-anchor': index === 0 ? 'start' : index === 3 ? 'end' : 'middle', fill: '#a9b4c7', 'font-size': 14}, label));
    }
    svg.append(svgNode('line', {x1: pad.left, x2: width-pad.right, y1: y(baseline), y2: y(baseline),
      stroke: colors.baseline, 'stroke-width': 1.6, 'stroke-dasharray': '6 5'}));
    function addLine(values, color, weight, opacity = 1) {
      const points = values.flatMap((value, index) => value === null ? [] : [`${x(index)},${y(value)}`]).join(' ');
      svg.append(svgNode('polyline', {points, fill: 'none', stroke: color, 'stroke-width': weight,
        opacity, 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'vector-effect': 'non-scaling-stroke'}));
    }
    addLine(games.map(game => game.fantasy_points), colors.game, 1.2, 0.6);
    for (let index = 0; index < games.length; index++) svg.append(svgNode('circle', {cx: x(index), cy: y(games[index].fantasy_points), r: 2, fill: colors.game, opacity: 0.7}));
    addLine(ten, colors.ten, 2.6);
    addLine(four, colors.four, 2.6);
    const guide = svgNode('line', {y1: pad.top, y2: height-pad.bottom, stroke: '#dae5f2', 'stroke-dasharray': '3 4', opacity: 0.45});
    const marker = svgNode('circle', {r: 4.5, fill: '#eff4ff', stroke: '#171c28', 'stroke-width': 2});
    svg.append(guide, marker);
    const readout = document.createElement('div');
    readout.className = 'trend-readout';
    readout.setAttribute('aria-live', 'polite');
    let selected = games.length - 1;
    function select(index) {
      selected = Math.max(0, Math.min(games.length-1, index));
      const game = games[selected];
      guide.setAttribute('x1', x(selected)); guide.setAttribute('x2', x(selected));
      marker.setAttribute('cx', x(selected)); marker.setAttribute('cy', y(game.fantasy_points));
      readout.textContent = `${game.date} · Game ${format(game.fantasy_points)} FP · 4-game ${format(four[selected])} · 10-game ${format(ten[selected])}`;
    }
    function inspectPointer(event) {
      const box = svg.getBoundingClientRect();
      const position = (event.clientX-box.left)/box.width*width;
      let nearest = 0;
      for (let index=1; index<games.length; index++) if (Math.abs(x(index)-position)<Math.abs(x(nearest)-position)) nearest=index;
      select(nearest);
    }
    svg.addEventListener('pointermove', inspectPointer);
    svg.addEventListener('pointerdown', inspectPointer);
    svg.addEventListener('keydown', event => {
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault(); select(selected + (event.key === 'ArrowLeft' ? -1 : 1));
      }
    });
    select(selected);
    const note = document.createElement('p');
    note.className = 'trend-note';
    const earlier = result.baseline_before_last_10;
    note.textContent = `Baseline ${format(baseline)} FP/G (${earlier.start_date}–${earlier.end_date}); shaded area = last 10 games. Hover, tap, or use arrow keys to inspect. A 4-game window is not a fixed calendar week.`;
    figure.append(caption, subtitle, legend, svg, readout, note);
    return figure;
  };
})();
