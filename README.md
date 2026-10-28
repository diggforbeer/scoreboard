# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                        |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/nhl\_scoreboard/\_\_init\_\_.py         |        1 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/\_\_main\_\_.py         |       45 |        3 |       10 |        2 |     91% | 58-59, 82 |
| src/nhl\_scoreboard/admin\_server.py        |      646 |       38 |      204 |       14 |     94% |683-\>681, 685-686, 691, 756-\>exit, 866-867, 874-875, 883-884, 991, 997, 1020-1021, 1110, 1113, 1137-\>1139, 1181, 1217, 1247, 1250-\>1261, 1479-1480, 1502-1521, 1525-1528, 1580, 1632 |
| src/nhl\_scoreboard/app.py                  |     1398 |       56 |      538 |       37 |     95% |362-\>366, 511-512, 539-\>541, 682-\>684, 685, 766-767, 776-\>775, 779-\>778, 805-806, 941, 1133-1134, 1261-1263, 1277, 1297-\>exit, 1344, 1366, 1383-\>1380, 1428, 1437, 1452, 1455, 1466, 1469, 1475, 1486, 1489, 1495, 1601, 1689, 1736, 1767-\>1769, 1777-1779, 1794-1796, 1841-1843, 1924-1926, 1958-1959, 1981-1982, 2040-2041, 2112, 2124, 2313, 2351, 2364, 2484, 2551, 2553, 2565 |
| src/nhl\_scoreboard/april\_fools.py         |       24 |        2 |        0 |        0 |     92% |     51-54 |
| src/nhl\_scoreboard/audio.py                |      117 |        2 |       34 |        0 |     99% |  219, 226 |
| src/nhl\_scoreboard/brightness.py           |        9 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/button.py               |       56 |        1 |        6 |        0 |     98% |        51 |
| src/nhl\_scoreboard/config.py               |      329 |        4 |       62 |        1 |     99% |338-339, 725-726 |
| src/nhl\_scoreboard/delay.py                |       28 |        1 |        6 |        0 |     97% |        33 |
| src/nhl\_scoreboard/demo.py                 |       64 |        0 |        8 |        0 |    100% |           |
| src/nhl\_scoreboard/display/\_\_init\_\_.py |        0 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/display/ascii.py        |       54 |        0 |        6 |        0 |    100% |           |
| src/nhl\_scoreboard/display/fonts.py        |       29 |        2 |        6 |        1 |     91% |     33-34 |
| src/nhl\_scoreboard/display/holiday.py      |      546 |        2 |      136 |        2 |     99% | 133, 1446 |
| src/nhl\_scoreboard/display/logos.py        |       86 |        9 |       22 |        1 |     89% |41, 91-95, 99-101 |
| src/nhl\_scoreboard/display/matrix.py       |       43 |        0 |        4 |        0 |    100% |           |
| src/nhl\_scoreboard/display/mirror.py       |      148 |        5 |       42 |        3 |     96% |98, 126, 176, 197, 217 |
| src/nhl\_scoreboard/display/renderer.py     |      692 |        5 |      254 |       10 |     98% |533, 540, 622-\>624, 761-\>763, 772-\>777, 1067, 1102, 1288-\>1317, 1303-\>1302, 1310 |
| src/nhl\_scoreboard/display/teams.py        |       16 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/light\_sensor.py        |       38 |        0 |        2 |        0 |    100% |           |
| src/nhl\_scoreboard/network.py              |       11 |        2 |        0 |        0 |     82% |     25-26 |
| src/nhl\_scoreboard/nhl/\_\_init\_\_.py     |        3 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/nhl/api.py              |      122 |       14 |        8 |        0 |     89% |122-124, 167-169, 177-182, 233-234 |
| src/nhl\_scoreboard/nhl/models.py           |      512 |        4 |      122 |        2 |     99% |234-235, 391, 559 |
| src/nhl\_scoreboard/setup\_server.py        |      134 |        1 |       30 |        3 |     98% |405, 425-\>429, 429-\>exit |
| src/nhl\_scoreboard/updater.py              |      233 |       24 |       52 |        8 |     89% |105-106, 124, 133, 151-155, 159-164, 231-236, 240-246, 257, 324-\>326, 351-\>353, 373-\>376, 377, 381 |
| src/nhl\_scoreboard/wifi.py                 |      140 |      109 |       28 |        0 |     18% |73-75, 94-142, 154-165, 169-171, 176-179, 183-185, 193-195, 203-213, 217-224, 228-240, 250-254, 261-265, 276-288, 292-296 |
| src/nhl\_scoreboard/wifi\_join.py           |       86 |        7 |       10 |        0 |     93% |112-114, 117-118, 201-202 |
| **TOTAL**                                   | **5610** |  **291** | **1590** |   **84** | **94%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/diggforbeer/scoreboard/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/diggforbeer/scoreboard/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fdiggforbeer%2Fscoreboard%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.