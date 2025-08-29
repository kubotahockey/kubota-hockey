$(document).ready(function() {
    $('#scoring-settings-form').on('submit', function(e) {
        e.preventDefault();
        
        let formData = $(this).serialize();  // Serialize form data
        
        $.ajax({
            type: 'POST',
            url: '/calculate_fantasy_points',
            data: formData,
            success: function(response) {
                $('#table-body').html(response);  // Inject the returned rows into the table body
                applyRanking();
                applySearch();
            },
            error: function(error) {
                console.error("Error calculating fantasy points:", error);
            }
        });
    });

    $('#export-csv').on('click', function() {
        let tableData = [];
        let headers = [];

        // Get table headers
        $('#player-data thead th').each(function() {
            headers.push($(this).text().trim());
        });
        tableData.push(headers);

        // Get table rows
        $('#player-data tbody tr').each(function() {
            let rowData = [];
            $(this).find('td').each(function() {
                rowData.push($(this).text().trim());
            });
            tableData.push(rowData);
        });

        // Send table data to server for CSV export
        $.ajax({
            type: 'POST',
            url: '/export_csv',
            contentType: 'application/json',
            data: JSON.stringify({ tableData: tableData }),
            success: function(response) {
                const url = window.URL.createObjectURL(new Blob([response]));
                const a = document.createElement('a');
                a.href = url;
                a.download = 'kubota_hockey_2024_2025.csv';  // Set the download filename here
                document.body.appendChild(a);
                a.click();
                a.remove();
            },
            error: function(error) {
                console.error("Error exporting CSV:", error);
            }
        });
    });

    $('#league-type').on('change', function() {
        const leagueType = $(this).val();
        
        if (leagueType === 'points') {
            // Set default values for Points League
            $('#g-points').val(6);         // Goals
            $('#a-points').val(4);         // Assists
            $('#sog-points').val(0.9);     // Shots on Goal
            $('#pim-points').val(0);       // Penalty Minutes
            $('#plusminus-points').val(2); // Plus/Minus
            $('#ppg-points').val(2);       // Power Play Goals
            $('#ppa-points').val(2);       // Power Play Assists
            $('#ppp-points').val(2);       // Power Play Points (PPP)
            $('#shg-points').val(0);       // Short-Handed Goals
            $('#sha-points').val(0);       // Short-Handed Assists
            $('#shp-points').val(0);       // Short-Handed Points (SHP)
            $('#blk-points').val(1);       // Blocked Shots
            $('#hit-points').val(0);       // Hits
            $('#fol-points').val(0);       // Faceoff Losses
            $('#fow-points').val(0);       // Faceoff Wins
            $('#defensive-points').val(1); // Defensive Points Multiplier
        } else if (leagueType === 'categories') {
            // Set default values for Categories League (all 1 by default, indicating inclusion)
            $('#g-points').val(1);         // Goals
            $('#a-points').val(1);         // Assists
            $('#sog-points').val(1);       // Shots on Goal
            $('#pim-points').val(0);       // Penalty Minutes
            $('#plusminus-points').val(0); // Plus/Minus
            $('#ppg-points').val(0);       // Power Play Goals
            $('#ppa-points').val(0);       // Power Play Assists
            $('#ppp-points').val(1);       // Power Play Points (PPP)
            $('#shg-points').val(0);       // Short-Handed Goals
            $('#sha-points').val(0);       // Short-Handed Assists
            $('#shp-points').val(0);       // Short-Handed Points (SHP)
            $('#blk-points').val(1);       // Blocked Shots
            $('#hit-points').val(1);       // Hits
            $('#fol-points').val(0);       // Faceoff Losses
            $('#fow-points').val(0);       // Faceoff Wins
            $('#defensive-points').val(0); // Defensive Points Multiplier
        }
    });

    // Handle dynamic roster settings based on position grouping
    $('#position-grouping').on('change', function() {
        const grouping = $(this).val();
        if (grouping === 'fw_def') {
            $('#roster-settings-split').hide();
            $('#roster-settings-fwdef').show();
        } else if (grouping === 'split') {
            $('#roster-settings-split').show();
            $('#roster-settings-fwdef').hide();
        }
    });

    // Apply ranking and sorting
    function applyRanking() {
        $('#table-body tr').each(function(index) {
            $(this).find('td:first').text(index + 1);
        });
    }
    
    // Apply search functionality
    $('#search-bar').on('keyup', function() {
        const searchTerm = $(this).val().toLowerCase();
        $('#table-body tr').filter(function() {
            $(this).toggle($(this).text().toLowerCase().indexOf(searchTerm) > -1);
        });
        
        applyRanking();  // Reapply ranking after filtering
    });

    // Apply sortable functionality to table headers
    $('#player-table thead th[data-sort]').on('click', function() {
        const sortKey = $(this).data('sort');
        const rows = $('#table-body tr').get();
        const isNumeric = $(this).data('numeric') || false;

        rows.sort(function(a, b) {
            const keyA = $(a).find(`td[data-key="${sortKey}"]`).text().toUpperCase();
            const keyB = $(b).find(`td[data-key="${sortKey}"]`).text().toUpperCase();

            if (isNumeric) {
                return parseFloat(keyA) - parseFloat(keyB);
            } else {
                if (keyA < keyB) return -1;
                if (keyA > keyB) return 1;
                return 0;
            }
        });

        // Toggle sort direction on subsequent clicks
        if ($(this).hasClass('ascending')) {
            rows.reverse();
            $(this).removeClass('ascending').addClass('descending');
        } else {
            $(this).removeClass('descending').addClass('ascending');
        }

        // Append sorted rows back to the table body
        $.each(rows, function(index, row) {
            $('#table-body').append(row);
        });

        applyRanking();  // Reapply ranking after sorting
    });
});
