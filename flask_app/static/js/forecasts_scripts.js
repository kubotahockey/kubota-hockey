document.addEventListener('DOMContentLoaded', function () {
  // DataTable init
  const table = $('#forecastsTable').DataTable({
    paging: true,
    pageLength: 15,
    lengthChange: false,
    searching: true,
    ordering: true,
    order: [[6, 'desc']], // PTS desc
    columnDefs: [
      { targets: '_all', className: 'dt-body-center' },
      // use data-order when present, fallback to text
      { targets: [3, 4, 5, 6, 7, 8, 9], orderDataType: 'dom-data-order' }
    ],
    drawCallback: function () {
      window.requestAnimationFrame(initializeBarCharts);
    }
  });

  // ------- DataTables plug-in: sort by data-order attr if present -------
  $.fn.dataTable.ext.order['dom-data-order'] = function (settings, col) {
    return this.api()
      .cells(null, col, { order: 'index' })
      .nodes()
      .map(function (td) {
        const v = td.getAttribute('data-order') || td.getAttribute('data-value') || td.textContent || '';
        const num = parseFloat(String(v).replace(/,/g, ''));
        return isNaN(num) ? v : num;
      });
  };

  // Round bar-cell data-values to 0 decimals (display/export consistency)
  table.columns([3, 4, 5, 6]).every(function () {
    this.nodes().to$().each(function () {
      const val = $(this).data('value');
      if ($.isNumeric(val)) {
        const r = Math.round(val);
        $(this).attr('data-value', r).attr('data-order', r);
      }
    });
  });

  // Debounced global search (if you have #searchBox in your layout)
  let searchTimeout;
  $('#searchBox').on('keyup', function () {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      table.search(this.value).draw();
    }, 300);
  });

  // Position filter (select)
  $('#positionFilter').on('change', function () {
    const position = this.value;
    if (position) {
      table.column(1).search('^' + position + '$', true, false).draw();
    } else {
      table.column(1).search('').draw();
    }
  });

  // Tooltips (if you use them)
  $('[data-toggle="tooltip"]').tooltip();

  // Initial bar charts
  initializeBarCharts();

  // ================= CSV Export =================
  $('#exportForecastsCsv').on('click', function () {
    const payload = buildCsvPayload(table);
    // POST to your existing Flask route
    $.ajax({
      type: 'POST',
      url: '/export_csv',
      contentType: 'application/json',
      data: JSON.stringify({ tableData: payload }),
      xhrFields: { responseType: 'blob' },
      success: function (blob) {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'kubota_hockey_7yr_forecasts.csv';
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      },
      error: function (err) {
        console.error('Error exporting CSV:', err);
      }
    });
  });

  /**
   * Build rows for CSV from the DataTable:
   * - Uses the 2nd header row (actual column labels, not the grouped header)
   * - Exports only rows matching current search + filters and current sort
   * - For bar cells, uses data-value (clean numbers)
   */
  function buildCsvPayload(dt) {
    const payload = [];

    // Header: take the 2nd <tr> (your real column labels)
    const $hdr = $('#forecastsTable thead tr').eq(1).find('th');
    const headers = $hdr
      .map(function () { return $(this).text().trim(); })
      .get();
    payload.push(headers);

    // Rows: filtered & sorted
    dt.rows({ search: 'applied', order: 'applied' }).every(function () {
      const node = this.node(); // <tr>
      const $cells = $(node).children('td');

      const row = [];
      $cells.each(function (idx) {
        const $td = $(this);

        // bar-cell columns (GP, G, A, PTS) have numeric values in data-value
        if ($td.hasClass('bar-cell')) {
          let v = $td.attr('data-value') || $td.attr('data-order') || $td.text().trim();
          if (v == null) v = '';
          row.push(v);
        } else {
          // plain text cell; strip link markup for Name
          row.push($td.text().trim());
        }
      });

      payload.push(row);
    });

    return payload;
  }
});

// --------- Your existing bar chart code (unchanged) ---------
function initializeBarCharts() {
  const maxValues = { GP: 500, G: 250, A: 500, PTS: 700, PIM: 1000 };

  d3.selectAll('.bar-cell').each(function () {
    const value = parseInt(d3.select(this).attr('data-value'));
    const column = d3.select(this).attr('data-column');
    const maxValue = maxValues[column];

    const colorScale = d3.scaleLinear()
      .domain([0, maxValue])
      .range(['#24155A', '#00e676']);
    const color = colorScale(value);

    d3.select(this).selectAll('canvas').remove();

    const canvasWidth = 85;
    const canvasHeight = 30;

    const canvas = d3.select(this)
      .append('canvas')
      .attr('width', canvasWidth)
      .attr('height', canvasHeight)
      .node();

    const ctx = canvas.getContext('2d');

    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: [''],
        datasets: [{
          data: [value],
          backgroundColor: [color]
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: false,
        maintainAspectRatio: false,
        scales: {
          x: { display: false, max: maxValue },
          y: { display: false }
        },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        layout: { padding: { top: 15 } },
        animation: false
      }
    });

    d3.select(this).append('div')
      .style('position', 'absolute')
      .style('top', '0')
      .style('width', canvasWidth + 'px')
      .style('text-align', 'center')
      .style('color', '#fff')
      .style('font-size', '14px')
      .text(value);
  });
}
