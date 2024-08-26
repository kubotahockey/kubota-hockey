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
            $('#g-points').val(6);
            $('#a-points').val(4);
            $('#sog-points').val(1);
            $('#pim-points').val(0);
            $('#plusminus-points').val(2);
            $('#ppg-points').val(2);
            $('#ppa-points').val(2);
            $('#shg-points').val(0);
            $('#sha-points').val(0);
            $('#blk-points').val(1);
            $('#hit-points').val(0);
            $('#fol-points').val(0);
            $('#fow-points').val(0);
        } else if (leagueType === 'categories') {
            // Set default values for Categories League (all 1 by default, indicating inclusion)
            $('#g-points').val(1);
            $('#a-points').val(1);
            $('#sog-points').val(1);
            $('#pim-points').val(0);
            $('#plusminus-points').val(0);
            $('#ppg-points').val(1);
            $('#ppa-points').val(1);
            $('#shg-points').val(0);
            $('#sha-points').val(0);
            $('#blk-points').val(0);
            $('#hit-points').val(1);
            $('#fol-points').val(0);
            $('#fow-points').val(0);
        }
    });
});