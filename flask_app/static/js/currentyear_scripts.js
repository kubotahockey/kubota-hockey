// ===========================
// Kubota Hockey - Table JS (Pos-only filter + global sort)
// ===========================
$(document).ready(function () {
  // ---------------------------
  // Helpers / Config
  // ---------------------------
  function getTableSelector() {
    if ($('#player-table').length) return '#player-table';
    if ($('#player-data').length) return '#player-data';
    return '#player-table';
  }
  function getTBodySelector() { return '#table-body'; }

  function applyRanking() {
    const $rows = $(`${getTBodySelector()} tr:visible`);
    $rows.each(function (i) { $(this).find('td').eq(0).text(i + 1); });
  }

  function parseNum(v) {
    if (v == null || v === '') return null;
    const n = Number(String(v).replace(/,/g, ''));
    return Number.isFinite(n) ? n : null;
  }

  // ---------------------------
  // Column detection + sorting
  // ---------------------------
  let CURRENT_COLS = [];
  let POS_COL_INDEX = null;

  function detectColumns() {
    const tableSel = getTableSelector();
    const cols = [];
    const $headerRow = $(`${tableSel} thead tr`).first();
    const $rows = $(`${getTBodySelector()} tr`);

    $headerRow.find('th').each(function (i) {
      const title = ($(this).text() || '').trim();
      const vals = $rows.map(function () {
        return ($(this).find('td').eq(i).text() || '').trim();
      }).get();

      const numeric = vals.filter(v => v !== '').every(v => !isNaN(parseFloat(v.replace(/,/g, ''))));
      cols.push({ index: i, title, type: numeric ? 'number' : 'text' });

      const t = title.toLowerCase();
      if (t === 'pos' || t === 'position') POS_COL_INDEX = i;
    });

    return cols;
  }

  /** Header: only Position gets a filter input; Rank (col 0) and others are blank */
  function ensureFilterRow() {
    const tableSel = getTableSelector();
    const $thead = $(`${tableSel} thead`);
    const $firstRow = $(`${tableSel} thead tr`).first();
    const colCount = $firstRow.children('th').length;

    $thead.find('tr.filters').remove();
    const $filters = $('<tr class="filters"></tr>');

    for (let i = 0; i < colCount; i++) {
      const $th = $('<th></th>');
      // no filter in first column (Rank) and only show input for Position column
      if (i === POS_COL_INDEX) {
        $th.append(`<input id="filter-pos" type="text" placeholder="Filter…" class="kh-filter kh-txt">`);
      }
      $filters.append($th);
    }

    $thead.append($filters);

    // Bind only the Pos filter
    $('#filter-pos').on('input', applyFilters);
  }

  /** Sorting on every header */
  function bindSorting(columns) {
    const tableSel = getTableSelector();
    const $ths = $(`${tableSel} thead tr`).first().find('th');
    $ths.css('cursor', 'pointer').off('click').on('click', function () {
      const idx = $(this).index();
      const col = columns[idx] || { type: 'text' };

      const rows = $(`${getTBodySelector()} tr`).get();
      rows.sort((a, b) => {
        const ta = $(a).find('td').eq(idx).text().trim();
        const tb = $(b).find('td').eq(idx).text().trim();
        if (col.type === 'number') {
          const na = parseNum(ta) ?? -Infinity;
          const nb = parseNum(tb) ?? -Infinity;
          return na - nb;
        }
        return ta.localeCompare(tb, undefined, { numeric: true, sensitivity: 'base' });
      });

      const asc = !$(this).hasClass('ascending');
      $(`${tableSel} thead th`).removeClass('ascending descending');
      $(this).addClass(asc ? 'ascending' : 'descending');
      if (!asc) rows.reverse();

      $.each(rows, function (_, row) {
        $(`${getTBodySelector()}`).append(row);
      });

      applyFilters(); // keep current filter applied
    });
  }

  // ---------------------------
  // Filtering (Pos-only + global search)
  // ---------------------------
  function applyFilters() {
    const posQuery = ($('#filter-pos').val() || '').toLowerCase().trim();
    const searchTerm = ($('#search-bar').val() || '').toLowerCase().trim();

    $(`${getTBodySelector()} tr`).each(function () {
      const $tr = $(this);
      let ok = true;

      // Position column filtering (OR across tokens typed e.g. "c rw" or "c,rw")
      if (ok && POS_COL_INDEX !== null && posQuery) {
        const parts = posQuery.split(/[,\s]+/).filter(Boolean);
        const cellTextRaw = ($tr.find('td').eq(POS_COL_INDEX).text() || '').toLowerCase();
        const tokens = cellTextRaw.replace(/\s+/g, '').split(',').filter(Boolean);
        const matchAny = parts.some(p => tokens.some(t => t.includes(p)));
        if (!matchAny) ok = false;
      }

      // Global search still applies (not a header filter)
      if (ok && searchTerm) {
        const all = $tr.text().toLowerCase();
        ok = all.includes(searchTerm);
      }

      $tr.toggle(ok);
    });

    applyRanking();
  }

  function refreshUI() {
    CURRENT_COLS = detectColumns();
    ensureFilterRow();     // builds only Pos filter
    bindSorting(CURRENT_COLS);
    applyFilters();
  }

  // ---------------------------
  // AJAX: Calculate Fantasy Points
  // ---------------------------
  $('#scoring-settings-form').on('submit', function (e) {
    e.preventDefault();
    const formData = $(this).serialize();

    $.ajax({
      type: 'POST',
      url: '/calculate_fantasy_points',
      data: formData,
      success: function (response) {
        $(`${getTBodySelector()}`).html(response); // returned <tr> rows
        applyRanking();
        refreshUI();
      },
      error: function (error) {
        console.error('Error calculating fantasy points:', error);
      }
    });
  });

  // ---------------------------
  // CSV Export (exports visible rows)
  // ---------------------------
  $('#export-csv').on('click', function () {
    const tableSel = getTableSelector();
    const tbodySel = getTBodySelector();

    const tableData = [];
    const headers = [];

    $(`${tableSel} thead th`).each(function () {
      headers.push($(this).text().trim());
    });
    tableData.push(headers);

    $(`${tbodySel} tr:visible`).each(function () {
      const rowData = [];
      $(this).find('td').each(function () {
        rowData.push($(this).text().trim());
      });
      tableData.push(rowData);
    });

    $.ajax({
      type: 'POST',
      url: '/export_csv',
      contentType: 'application/json',
      data: JSON.stringify({ tableData }),
      xhrFields: { responseType: 'blob' },
      success: function (blob) {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'kubota_hockey_2024_2025.csv';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      },
      error: function (error) {
        console.error('Error exporting CSV:', error);
      }
    });
  });

  // ---------------------------
  // League-type defaults
  // ---------------------------
  $('#league-type').on('change', function () {
    const leagueType = $(this).val();

    if (leagueType === 'points') {
      $('#g-points').val(6);
      $('#a-points').val(4);
      $('#sog-points').val(0.9);
      $('#pim-points').val(0);
      $('#plusminus-points').val(2);
      $('#ppg-points').val(2);
      $('#ppa-points').val(2);
      $('#ppp-points').val(2);
      $('#shg-points').val(0);
      $('#sha-points').val(0);
      $('#shp-points').val(0);
      $('#blk-points').val(1);
      $('#hit-points').val(0);
      $('#fol-points').val(0);
      $('#fow-points').val(0);
      $('#defensive-points').val(1);
    } else if (leagueType === 'categories') {
      $('#g-points').val(1);
      $('#a-points').val(1);
      $('#sog-points').val(1);
      $('#pim-points').val(0);
      $('#plusminus-points').val(0);
      $('#ppg-points').val(0);
      $('#ppa-points').val(0);
      $('#ppp-points').val(1);
      $('#shg-points').val(0);
      $('#sha-points').val(0);
      $('#shp-points').val(0);
      $('#blk-points').val(1);
      $('#hit-points').val(1);
      $('#fol-points').val(0);
      $('#fow-points').val(0);
      $('#defensive-points').val(0);
    }
  });

  // ---------------------------
  // Position grouping toggles
  // ---------------------------
  $('#position-grouping').on('change', function () {
    const grouping = $(this).val();
    if (grouping === 'fw_def') {
      $('#roster-settings-split').hide();
      $('#roster-settings-fwdef').show();
    } else if (grouping === 'split') {
      $('#roster-settings-split').show();
      $('#roster-settings-fwdef').hide();
    }
  });

  // ---------------------------
  // Global search ties into filters
  // ---------------------------
  $('#search-bar').off('keyup').on('keyup', applyFilters);

  // ---------------------------
  // Initialize on page load
  // ---------------------------
  refreshUI();
});
