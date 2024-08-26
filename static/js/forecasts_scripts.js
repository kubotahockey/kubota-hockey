document.addEventListener('DOMContentLoaded', function() {
    const table = $('#forecastsTable').DataTable({
        paging: true,
        pageLength: 15,
        lengthChange: false,
        searching: true,
        ordering: true,
        order: [[6, 'desc']], // Order by Points (PTS) column, highest to lowest
        columnDefs: [
            { targets: '_all', className: 'dt-body-center' },
            { targets: [3, 4, 5, 6, 7], orderDataType: 'dom-text-numeric' }
        ],
        drawCallback: function() {
            window.requestAnimationFrame(initializeBarCharts); // Reinitialize bar charts on each draw using requestAnimationFrame
        }
    });

    // Round values to 0 decimal places
    table.columns([3, 4, 5, 6, 7]).every(function() {
        this.nodes().to$().each(function() {
            const cellValue = $(this).data('value');
            if ($.isNumeric(cellValue)) {
                $(this).attr('data-value', Math.round(cellValue));
            }
        });
    });

    // Debounce search input to improve performance
    let searchTimeout;
    $('#searchBox').on('keyup', function() {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            table.search(this.value).draw();
        }, 300); // Adjust debounce delay as needed
    });

    // Add filter functionality to the position dropdown
    $('#positionFilter').on('change', function() {
        const position = this.value;
        if (position) {
            table.column(1).search('^' + position + '$', true, false).draw(); // Exact match search
        } else {
            table.column(1).search('').draw(); // Reset search
        }
    });

    // Initialize tooltips
    $('[data-toggle="tooltip"]').tooltip();

    // Initialize bar charts on initial load
    initializeBarCharts();
});

// Function to initialize horizontal bar charts using Chart.js
function initializeBarCharts() {
    const maxValues = { GP: 500, G: 250, A: 500, PTS: 700, PIM: 1000 }; // Define max values for scaling

    d3.selectAll('.bar-cell').each(function() {
        const value = parseInt(d3.select(this).attr('data-value'));
        const column = d3.select(this).attr('data-column');
        const maxValue = maxValues[column];

        // Define the color based on the value
        const colorScale = d3.scaleLinear()
            .domain([0, maxValue])
            .range(['#24155A', '#00e676']); // Adjust colors as needed
        const color = colorScale(value);

        // Clear previous canvas elements if any
        d3.select(this).selectAll('canvas').remove();

        const canvasWidth = 85; // Adjust width as needed
        const canvasHeight = 30; // Adjust height as needed

        // Append a canvas element
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
                indexAxis: 'y', // Horizontal bar chart
                responsive: false,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        display: false,
                        max: maxValue
                    },
                    y: {
                        display: false
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        enabled: false
                    }
                },
                layout: {
                    padding: {
                        top: 15 // Space for the text above
                    }
                },
                animation: false
            }
        });

        // Add text above the bar
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