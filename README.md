# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                        |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/nhl\_scoreboard/\_\_init\_\_.py         |        1 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/\_\_main\_\_.py         |       45 |        3 |       10 |        2 |     91% | 58-59, 82 |
| src/nhl\_scoreboard/admin\_server.py        |      638 |       36 |      196 |       12 |     94% |674-\>672, 676-677, 682, 747-\>exit, 857-858, 865-866, 874-875, 978, 984, 1007-1008, 1114-\>1116, 1158, 1194, 1224, 1227-\>1238, 1456-1457, 1479-1498, 1502-1505, 1557, 1609 |
| src/nhl\_scoreboard/app.py                  |     1241 |       53 |      474 |       27 |     95% |328-\>332, 469-470, 497-\>499, 629-\>631, 632, 697-\>696, 700-\>699, 726-727, 861, 1153-1155, 1169, 1189-\>exit, 1236, 1258, 1275-\>1272, 1320, 1329, 1340-1346, 1430, 1499-1500, 1512, 1559, 1596-1598, 1613-1615, 1654-1656, 1701-1703, 1735-1736, 1758-1759, 1817-1818, 1889, 1901, 2070, 2107, 2120, 2239, 2293, 2295, 2307 |
| src/nhl\_scoreboard/april\_fools.py         |       24 |        2 |        0 |        0 |     92% |     51-54 |
| src/nhl\_scoreboard/audio.py                |      100 |        2 |       30 |        0 |     98% |  180, 187 |
| src/nhl\_scoreboard/brightness.py           |        9 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/button.py               |       56 |        1 |        6 |        0 |     98% |        51 |
| src/nhl\_scoreboard/config.py               |      327 |        4 |       62 |        1 |     99% |330-331, 714-715 |
| src/nhl\_scoreboard/demo.py                 |       58 |        0 |        8 |        0 |    100% |           |
| src/nhl\_scoreboard/display/\_\_init\_\_.py |        0 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/display/ascii.py        |       54 |        0 |        6 |        0 |    100% |           |
| src/nhl\_scoreboard/display/fonts.py        |       29 |        2 |        6 |        1 |     91% |     33-34 |
| src/nhl\_scoreboard/display/holiday.py      |      546 |        2 |      136 |        2 |     99% | 133, 1446 |
| src/nhl\_scoreboard/display/logos.py        |       86 |        9 |       22 |        1 |     89% |41, 91-95, 99-101 |
| src/nhl\_scoreboard/display/matrix.py       |       43 |        0 |        4 |        0 |    100% |           |
| src/nhl\_scoreboard/display/mirror.py       |      148 |        5 |       42 |        3 |     96% |98, 126, 176, 197, 217 |
| src/nhl\_scoreboard/display/renderer.py     |      621 |        4 |      214 |        7 |     99% |531, 538, 620-\>622, 759-\>761, 770-\>775, 953, 988 |
| src/nhl\_scoreboard/display/teams.py        |       16 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/light\_sensor.py        |       38 |        0 |        2 |        0 |    100% |           |
| src/nhl\_scoreboard/nhl/\_\_init\_\_.py     |        3 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/nhl/api.py              |      122 |       14 |        8 |        0 |     89% |122-124, 167-169, 177-182, 233-234 |
| src/nhl\_scoreboard/nhl/models.py           |      497 |        4 |      118 |        2 |     99% |234-235, 391, 559 |
| src/nhl\_scoreboard/setup\_server.py        |      134 |        1 |       30 |        3 |     98% |405, 425-\>429, 429-\>exit |
| src/nhl\_scoreboard/updater.py              |      215 |       24 |       48 |        8 |     88% |98-99, 117, 126, 144-148, 152-157, 197-202, 206-212, 223, 290-\>292, 311-\>313, 333-\>336, 337, 341 |
| src/nhl\_scoreboard/wifi.py                 |      140 |      109 |       28 |        0 |     18% |73-75, 94-142, 154-165, 169-171, 176-179, 183-185, 193-195, 203-213, 217-224, 228-240, 250-254, 261-265, 276-288, 292-296 |
| src/nhl\_scoreboard/wifi\_join.py           |       86 |        7 |       10 |        0 |     93% |112-114, 117-118, 201-202 |
| **TOTAL**                                   | **5277** |  **282** | **1460** |   **69** | **94%** |           |


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