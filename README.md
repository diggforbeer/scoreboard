# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                        |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/nhl\_scoreboard/\_\_init\_\_.py         |        1 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/\_\_main\_\_.py         |       45 |        3 |       10 |        2 |     91% | 58-59, 82 |
| src/nhl\_scoreboard/admin\_server.py        |      676 |       42 |      218 |       16 |     93% |685-\>683, 687-688, 693, 758-\>exit, 868-869, 876-877, 885-886, 997, 1003, 1026-1027, 1098-1099, 1141, 1144, 1147, 1150, 1174-\>1176, 1218, 1254, 1284, 1287-\>1298, 1531-1532, 1554-1573, 1577-1580, 1632, 1684 |
| src/nhl\_scoreboard/app.py                  |     1405 |       56 |      542 |       37 |     95% |363-\>367, 512-513, 540-\>542, 683-\>685, 686, 767-768, 777-\>776, 780-\>779, 806-807, 943, 1135-1136, 1269-1271, 1285, 1305-\>exit, 1352, 1374, 1391-\>1388, 1436, 1445, 1464, 1467, 1487, 1490, 1496, 1507, 1510, 1516, 1622, 1710, 1757, 1788-\>1790, 1798-1800, 1815-1817, 1862-1864, 1945-1947, 1979-1980, 2002-2003, 2061-2062, 2133, 2145, 2334, 2372, 2385, 2505, 2572, 2574, 2586 |
| src/nhl\_scoreboard/april\_fools.py         |       24 |        2 |        0 |        0 |     92% |     51-54 |
| src/nhl\_scoreboard/audio.py                |      130 |        2 |       38 |        0 |     99% |  242, 249 |
| src/nhl\_scoreboard/brightness.py           |        9 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/button.py               |       56 |        1 |        6 |        0 |     98% |        51 |
| src/nhl\_scoreboard/config.py               |      330 |        4 |       62 |        1 |     99% |338-339, 728-729 |
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
| src/nhl\_scoreboard/nhl/models.py           |      515 |        4 |      122 |        2 |     99% |234-235, 391, 559 |
| src/nhl\_scoreboard/setup\_server.py        |      134 |        1 |       30 |        3 |     98% |405, 425-\>429, 429-\>exit |
| src/nhl\_scoreboard/updater.py              |      233 |       24 |       52 |        8 |     89% |105-106, 124, 133, 151-155, 159-164, 231-236, 240-246, 257, 324-\>326, 351-\>353, 373-\>376, 377, 381 |
| src/nhl\_scoreboard/wifi.py                 |      140 |      109 |       28 |        0 |     18% |73-75, 94-142, 154-165, 169-171, 176-179, 183-185, 193-195, 203-213, 217-224, 228-240, 250-254, 261-265, 276-288, 292-296 |
| src/nhl\_scoreboard/wifi\_join.py           |       86 |        7 |       10 |        0 |     93% |112-114, 117-118, 201-202 |
| **TOTAL**                                   | **5664** |  **295** | **1612** |   **86** | **94%** |           |


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