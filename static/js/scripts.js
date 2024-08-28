document.addEventListener('DOMContentLoaded', () => {
    const players = JSON.parse(document.getElementById('playersList').textContent);
    const urlParams = new URLSearchParams(window.location.search);
    const queryPlayerName = urlParams.get('player');
    const randomPlayerName = queryPlayerName || JSON.parse(document.getElementById('randomPlayerName').textContent);
    const playerSearch = document.getElementById('playerSearch');
    const searchResults = document.getElementById('searchResults');

    // Function to fetch and display player data
    function fetchAndDisplayPlayerData(playerName) {
        console.log('Fetching data for player:', playerName);
        $.post('/get_player_data', { player_name: playerName })
            .done(function(response) {
                if (response.error) {
                    console.error('Error from server:', response.error);
                    alert(response.error);
                    return;
                }

                const player = response.projection[0];
                const comps = response.comps;
                const imageLink = response.image_link;

                if (!player || !comps) {
                    console.error('Incomplete data received from server:', response);
                    alert('Incomplete data received from server.');
                    return;
                }

                displayPlayerData(player, imageLink);
                displayPlayerChart(player, comps);
                displayPlayerComparisons(comps.slice(0, 10)); // Limit to top 10 comparables
                displayPlayerPercentiles(player);
            })
            .fail(function(jqXHR, textStatus, errorThrown) {
                console.error('AJAX request failed:', textStatus, errorThrown);
                alert('Failed to load player data.');
            });
    }

    // Function to display random player on page load
    function loadRandomPlayer() {
        fetchAndDisplayPlayerData(randomPlayerName);
    }

    // Function to display player data
    function displayPlayerData(player, imageLink) {
        if (player) {
            let playerStatsHTML = `
                 <div class="card text-white bg-dark mb-3">
                <div class="card-body">
                    <h2 class="card-title"><a href="forecasts.html?player=${player.name}" class="text-white">${player.name}</a></h2>
                    <div class="info-row">
                        <p><strong>Age:</strong> ${player.age}</p>
                        <p><strong>Position:</strong> ${player.fw_def}</p>
                    </div>
                    <div class="info-row">
                        <p><strong>Height:</strong> ${player.Height}</p>
                        <p><strong>Weight:</strong> ${player.Weight}</p>
                    </div>
                    <div class="info-row">
                        <p><strong>Draft Year:</strong> ${player.draft_year}</p>
                        <p><strong>Draft Pick:</strong> ${player.pick_number}</p>
                    </div>
                </div>
                <div class="card-body text-left">
                    <img src="/static/images/logo_teams/${imageLink}" alt="${player.name} team logo" class="img-fluid mt-3">
                </div>
            </div>`;
            
            document.getElementById('playerStats').innerHTML = playerStatsHTML;

            let playerProjectionsHTML = `
                <div class="container-fluid">
                    <div class="row">
                        <div class="col-sm-3 col-md-3 col-lg-3 mb-1">
                            <div class="card text-white bg-dark text-center">
                                <div class="card-body">
                                    <h5 class="card-title">Projected GP</h5>
                                    <p class="projected-stat">${Math.round(player.GP2)}</p>
                                </div>
                            </div>
                        </div>
                        <div class="col-sm-3 col-md-3 col-lg-3 mb-1">
                            <div class="card text-white bg-dark text-center">
                                <div class="card-body">
                                    <h5 class="card-title">Projected Goals</h5>
                                    <p class="projected-stat">${Math.round(player.GTOT)}</p>
                                </div>
                            </div>
                        </div>
                        <div class="col-sm-3 col-md-3 col-lg-3 mb-1">
                            <div class="card text-white bg-dark text-center">
                                <div class="card-body">
                                    <h5 class="card-title">Projected Assists</h5>
                                    <p class="projected-stat">${Math.round(player.ATOT)}</p>
                                </div>
                            </div>
                        </div>
                        <div class="col-sm-3 col-md-3 col-lg-3 mb-1">
                            <div class="card text-white bg-dark text-center">
                                <div class="card-body">
                                    <h5 class="card-title">Projected Points</h5>
                                    <p class="projected-stat">${Math.round(player.PTSTOT)}</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>`;

            document.getElementById('playerProjections').innerHTML = playerProjectionsHTML;
        }
    }

    // Function to display player percentiles
    function displayPlayerPercentiles(player) {
        const percentiles = {
            GPPercentile: player.GPPercentile,
            GPercentile: player.GPercentile,
            APercentile: player.APercentile,
            PTSPercentile: player.PTSPercentile
        };

        let percentileHTML = `
            <div class="col-12">
                <div class="row text-center">
                    <div class="col-sm-3">
                        <div class="chart-container">
                            <div class="chart-title">GP Percentile</div>
                            <canvas id="gpPercentileChart"></canvas>
                            <div class="chart-value">${(percentiles.GPPercentile * 100).toFixed(2)}%</div>
                        </div>
                    </div>
                    <div class="col-sm-3">
                        <div class="chart-container">
                            <div class="chart-title">Goals Percentile</div>
                            <canvas id="gPercentileChart"></canvas>
                            <div class="chart-value">${(percentiles.GPercentile * 100).toFixed(2)}%</div>
                        </div>
                    </div>
                    <div class="col-sm-3">
                        <div class="chart-container">
                            <div class="chart-title">Assists Percentile</div>
                            <canvas id="aPercentileChart"></canvas>
                            <div class="chart-value">${(percentiles.APercentile * 100).toFixed(2)}%</div>
                        </div>
                    </div>
                    <div class="col-sm-3">
                        <div class="chart-container">
                            <div class="chart-title">Points Percentile</div>
                            <canvas id="ptsPercentileChart"></canvas>
                            <div class="chart-value">${(percentiles.PTSPercentile * 100).toFixed(2)}%</div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.getElementById('playerPercentiles').innerHTML = percentileHTML;

        const createPercentileChart = (ctx, label, percentile) => {
            new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: ['Achieved', 'Remaining'],
                    datasets: [{
                        data: [percentile * 100, 100 - (percentile * 100)],
                        backgroundColor: ['#00e676', '#24155A'],
                        borderColor: ['#00e676', '#24155A'],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '70%',
                    plugins: {
                        legend: {
                            display: false
                        },
                        tooltip: {
                            callbacks: {
                                label: function (tooltipItem) {
                                    return tooltipItem.label + ': ' + tooltipItem.raw.toFixed(2) + '%';
                                }
                            }
                        }
                    }
                }
            });
        };

        createPercentileChart(document.getElementById('gpPercentileChart').getContext('2d'), 'GP Percentile', percentiles.GPPercentile);
        createPercentileChart(document.getElementById('gPercentileChart').getContext('2d'), 'Goals Percentile', percentiles.GPercentile);
        createPercentileChart(document.getElementById('aPercentileChart').getContext('2d'), 'Assists Percentile', percentiles.APercentile);
        createPercentileChart(document.getElementById('ptsPercentileChart').getContext('2d'), 'Points Percentile', percentiles.PTSPercentile);
    }

function displayPlayerChart(player, comps) {
    if (player) {
        let html = `<canvas id="playerLineChart" width="500" height="500"></canvas>`;
        playerChart.innerHTML = html;

        const ctx = document.getElementById('playerLineChart').getContext('2d');

        const labels = ['Two Years Prior', 'Prior Year', 'Year 1', 'Year 2', 'Year 3', 'Year 4','Year 5','Year 6', 'Year 7'];
        const playerData = [
            player.adjusted_pts_gp_lag2,
            player.adjusted_pts_gp_lag1,
            player.PT_Y1,
            player.PT_Y2,
            player.PT_Y3,
            player.PT_Y4,
            player.PT_Y5,
            player.PT_Y6,
            player.PT_Y7
        ];

        // Player's dataset
        const playerDataSet = {
            label: player.name + ' Projection',
            data: playerData,
            borderColor: 'rgba(46, 204, 113, 1)', // Teal color for the main player
            backgroundColor: 'rgba(46, 204, 113, 0)', // Light teal fill
            borderWidth: 3,
            fill: false,
            tension: 0.4, // Smooths the line
            pointStyle: 'circle',
            pointRadius: 6, // Larger point size for better visibility
            showLine: true
        };

        // Sorting the comparables by SCORE in descending order and selecting the top 3
        const selectedComps = comps.sort((a, b) => b.SCORE - a.SCORE).slice(0, 3);

        // Define colors for comparables
        const colors = [
            'rgba(255, 105, 97, 1)', // Pastel Red
            'rgba(255, 179, 71, 1)', // Pastel Orange
            'rgba(255, 255, 0, 1)'   // Yellow
        ];

        const compDataSets = selectedComps.map((comp, index) => {
            const compData = [
                comp.adjusted_pts_gp_lag2,
                comp.adjusted_pts_gp_lag1,
                comp.PTS_GPY1,
                comp.PTS_GPY2,
                comp.PTS_GPY3,
                comp.PTS_GPY4,
                comp.PTS_GPY5,
                comp.PTS_GPY6,
                comp.PTS_GPY7
            ];
            return {
                label: comp.Comparables,
                data: compData,
                borderColor: colors[index],
                backgroundColor: 'rgba(0, 0, 0, 0)', // No fill
                borderWidth: 1,
                fill: false,
                tension: 0.4,
                pointStyle: 'circle', // Consistent shape for comparables
                pointRadius: 5, // Uniform size
                showLine: true,
                borderDash: [5, 5] // Dotted lines for comparables
            };
        });

        new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [playerDataSet, ...compDataSets]
            },
            options: {
                scales: {
                    y: {
                        beginAtZero: false,
                        max: 2,
                        ticks: {
                            color: 'rgba(255, 255, 255, 0.7)' // Lighter white color for ticks
                        },
                        grid: {
                            color: 'rgba(77, 77, 77, 0.8)' // Darker gray color for grid lines
                        },
                        scaleLabel: {
                            display: true,
                            labelString: 'Points per Game',
                            color: 'white',
                            font: {
                                size: 14
                            }
                        }
                    },
                    x: {
                        ticks: {
                            color: 'rgba(255, 255, 255, 0.7)' // Lighter white color for x-axis ticks
                        },
                        grid: {
                            color: 'rgba(77, 77, 77, 0.8)' // Darker gray color for grid lines
                        }
                    }
                },
                plugins: {
                    legend: {
                        labels: {
                            color: 'white', // White text for legend
                            usePointStyle: true
                        }
                    },
                    title: {
                        display: true,
                        text: '7 Year Point per Game Projection - Top 3 Comparables',
                        color: 'white', // Title color
                        font: {
                            size: 16
                        }
                    },
                    tooltip: {
                        enabled: true,
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            label: function(tooltipItem) {
                                return `${tooltipItem.dataset.label}: ${tooltipItem.raw.toFixed(2)}`;
                            }
                        }
                    }
                },
                responsive: true,
                maintainAspectRatio: false
            }
        });
    }
}

    function displayPlayerComparisons(comps) {
        let playerComparisonsDiv = document.getElementById('playerComparisons');

        // Determine the maximum values for scaling the bar widths
        let maxScore = Math.max(...comps.map(comp => parseFloat(comp.SCORE).toFixed(2)));
        let maxGP = Math.max(...comps.map(comp => Math.round(comp.GPproj)));
        let maxPIM = Math.max(...comps.map(comp => Math.round(comp.PIMproj)));
        let maxGoals = Math.max(...comps.map(comp => Math.round(comp.Gproj)));
        let maxAssists = Math.max(...comps.map(comp => Math.round(comp.Aproj)));
        let maxPoints = Math.max(...comps.map(comp => Math.round(comp.Gproj + comp.Aproj))); // Assuming Points is the sum of Goals and Assists

        if (comps && comps.length > 0) {
            let tableHtml = `
                <table class="table table-dark table-hover">
                    <thead>
                        <tr>
                            <th colspan="6">Player Information</th>
                            <th colspan="7">7 Year Statistics</th>
                        </tr>
                        <tr>
                            <th style="text-align: left;">Name</th>
                            <th>Age</th>
                            <th>Height</th>
                            <th>Weight</th>
                            <th>Pick Number</th>
                            <th class="separator">Season</th>
                            <th>SCORE</th>
                            <th>GP</th>
                            <th>Goals</th>
                            <th>Assists</th>
                            <th>Points</th>
                            <th>PIM</th>
                        </tr>
                    </thead>
                    <tbody>`;

            comps.forEach(comp => {
                let roundedScore = parseFloat(comp.SCORE).toFixed(2);
                let roundedGP = Math.round(comp.GPproj);
                let roundedPIM = Math.round(comp.PIMproj);
                let roundedGoals = Math.round(comp.Gproj);
                let roundedAssists = Math.round(comp.Aproj);
                let roundedPoints = Math.round(comp.Gproj + comp.Aproj);

                tableHtml += `
                    <tr>
                        <td style="text-align: left;">${comp.Comparables}</td>
                        <td>${comp.age}</td>
                        <td>${comp.Height}</td>
                        <td>${comp.Weight}</td>
                        <td>${comp.pick_number}</td>
                        <td class="separator">${comp.season}</td>
                        <td>
                            <div class="bar-container">
                                <div class="bar-label">${roundedScore}</div>
                                <div class="bar bar-score" style="width: ${(roundedScore / maxScore) * 100}%"></div>
                            </div>
                        </td>
                        <td>
                            <div class="bar-container">
                                <div class="bar-label">${roundedGP}</div>
                                <div class="bar" style="width: ${(roundedGP / maxGP) * 100}%"></div>
                            </div>
                        </td>
                        <td>
                            <div class="bar-container">
                                <div class="bar-label">${roundedGoals}</div>
                                <div class="bar" style="width: ${(roundedGoals / maxGoals) * 100}%"></div>
                            </div>
                        </td>
                        <td>
                            <div class="bar-container">
                                <div class="bar-label">${roundedAssists}</div>
                                <div class="bar" style="width: ${(roundedAssists / maxAssists) * 100}%"></div>
                            </div>
                        </td>
                        <td>
                            <div class="bar-container">
                                <div class="bar-label">${roundedPoints}</div>
                                <div class="bar" style="width: ${(roundedPoints / maxPoints) * 100}%"></div>
                            </div>
                        </td>
                        <td>
                            <div class="bar-container">
                                <div class="bar-label">${roundedPIM}</div>
                                <div class="bar" style="width: ${(roundedPIM / maxPIM) * 100}%"></div>
                            </div>
                        </td>
                    </tr>`;
            });

            tableHtml += `</tbody></table>`;
            playerComparisonsDiv.innerHTML = tableHtml;
        } else {
            playerComparisonsDiv.innerHTML = '<p class="text-white">No comparable players found.</p>';
        }
    }

    function exportToPNG() {
        // Function to copy computed styles
        function copyComputedStyle(sourceNode, targetNode) {
            const computedStyle = window.getComputedStyle(sourceNode);
            for (const key of computedStyle) {
                targetNode.style[key] = computedStyle[key];
            }
        }

        // Clone nodes with computed styles
        function cloneNodeWithStyles(node) {
            const clone = node.cloneNode(true);
            copyComputedStyle(node, clone);
            if (node.children) {
                for (let i = 0; i < node.children.length; i++) {
                    clone.replaceChild(cloneNodeWithStyles(node.children[i]), clone.children[i]);
                }
            }
            return clone;
        }

        // Capture the relevant sections
        const playerInfo = document.getElementById('playerStats');
        const projections = document.getElementById('playerProjections');
        const percentiles = document.getElementById('playerPercentiles');
        const comparisons = document.getElementById('playerComparisons');

        // Create a new container to hold all sections
        const exportContainer = document.createElement('div');
        exportContainer.id = 'exportContainer';
        exportContainer.style.backgroundColor = '#000'; // Ensure background color is set for better contrast

        // Apply consistent font styling to export container
        exportContainer.style.fontFamily = 'Arial, sans-serif';
        exportContainer.style.color = 'white';

        // Add the player info and comparisons side by side
        const playerInfoContainer = document.createElement('div');
        playerInfoContainer.style.display = 'flex';
        playerInfoContainer.style.justifyContent = 'space-between';

        const playerInfoSection = cloneNodeWithStyles(playerInfo);
        const comparisonsSection = cloneNodeWithStyles(comparisons);

        playerInfoContainer.appendChild(playerInfoSection);
        playerInfoContainer.appendChild(comparisonsSection);

        exportContainer.appendChild(playerInfoContainer);
        exportContainer.appendChild(cloneNodeWithStyles(projections));
        exportContainer.appendChild(cloneNodeWithStyles(percentiles));

        // Append the export container to the body (hidden)
        exportContainer.style.position = 'absolute';
        exportContainer.style.top = '-9999px';
        document.body.appendChild(exportContainer);

        // Ensure all images are fully loaded before capturing
        const images = exportContainer.getElementsByTagName('img');
        let imagesLoaded = 0;

        for (const image of images) {
            if (image.complete) {
                imagesLoaded++;
            } else {
                image.onload = () => {
                    imagesLoaded++;
                    if (imagesLoaded === images.length) {
                        captureScreenshot();
                    }
                };
                image.onerror = () => {
                    imagesLoaded++;
                    if (imagesLoaded === images.length) {
                        captureScreenshot();
                    }
                };
            }
        }

        if (imagesLoaded === images.length) {
            captureScreenshot();
        }

        function captureScreenshot() {
            // Use html2canvas to capture the export container
            html2canvas(exportContainer, {
                backgroundColor: '#000', // Ensure background color
                scale: 2, // Improve resolution
                useCORS: true // Allow cross-origin images
            }).then(canvas => {
                // Create a link element to download the image
                const link = document.createElement('a');
                link.href = canvas.toDataURL('image/png');
                link.download = 'player_info.png';
                link.click();

                // Remove the export container from the DOM
                document.body.removeChild(exportContainer);
            });
        }
    }

    // Load the random player on page load
    loadRandomPlayer();

    // Add event listener to the search input
    playerSearch.addEventListener('input', function() {
        const query = this.value.toLowerCase();
        searchResults.innerHTML = '';

        if (query.length > 0) {
            const filteredPlayers = players.filter(player => player.toLowerCase().includes(query));
            filteredPlayers.slice(0, 5).forEach(player => {
                const li = document.createElement('li');
                li.className = 'list-group-item list-group-item-action bg-dark text-white';
                li.textContent = player;
                li.addEventListener('click', function() {
                    fetchAndDisplayPlayerData(player);
                    searchResults.innerHTML = '';
                    playerSearch.value = '';
                });
                searchResults.appendChild(li);
            });
        }
    });

    // Add event listener to the export button
    document.getElementById('exportButton').addEventListener('click', exportToPNG);
});
