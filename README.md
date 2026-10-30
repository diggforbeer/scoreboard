# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                        |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/nhl\_scoreboard/\_\_init\_\_.py         |        1 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/\_\_main\_\_.py         |       48 |        4 |       12 |        3 |     88% |56, 61-62, 85 |
| src/nhl\_scoreboard/admin\_server.py        |      711 |       47 |      226 |       17 |     93% |697-\>695, 699-700, 705, 770-\>exit, 880-881, 888-889, 897-898, 1010, 1016, 1023-1025, 1039-1040, 1111-1112, 1154, 1157, 1160, 1163, 1187-\>1189, 1231, 1267, 1297, 1300-\>1311, 1330-\>1333, 1581-1582, 1604-1623, 1627-1630, 1686, 1717-1719, 1758 |
| src/nhl\_scoreboard/app.py                  |     1461 |       57 |      562 |       39 |     95% |377-\>381, 520-521, 548-\>550, 692-\>694, 695, 697, 779-780, 789-\>788, 792-\>791, 819-820, 957, 1140-1141, 1274-1276, 1290, 1310-\>exit, 1379, 1401, 1418-\>1415, 1463, 1472, 1491, 1494, 1514, 1517, 1523, 1534, 1537, 1543, 1649, 1737, 1784, 1815-\>1817, 1825-1827, 1842-1844, 1889-1891, 1909, 1928-\>1930, 1933, 2035-2037, 2069-2070, 2092-2093, 2151-2152, 2226, 2238, 2427, 2465, 2478, 2599, 2688 |
| src/nhl\_scoreboard/april\_fools.py         |       24 |        2 |        0 |        0 |     92% |     51-54 |
| src/nhl\_scoreboard/audio.py                |      130 |        2 |       38 |        0 |     99% |  242, 249 |
| src/nhl\_scoreboard/audio\_normalize.py     |      132 |       19 |       36 |        6 |     82% |86-87, 111, 128, 130-143, 154, 158, 161-163, 165, 173 |
| src/nhl\_scoreboard/blowout.py              |       23 |        0 |       10 |        0 |    100% |           |
| src/nhl\_scoreboard/brightness.py           |        9 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/button.py               |       56 |        1 |        6 |        0 |     98% |        51 |
| src/nhl\_scoreboard/config.py               |      335 |        4 |       62 |        1 |     99% |342-343, 745-746 |
| src/nhl\_scoreboard/delay.py                |       28 |        1 |        6 |        0 |     97% |        33 |
| src/nhl\_scoreboard/demo.py                 |       73 |        0 |       10 |        0 |    100% |           |
| src/nhl\_scoreboard/display/\_\_init\_\_.py |        0 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/display/ascii.py        |       54 |        0 |        6 |        0 |    100% |           |
| src/nhl\_scoreboard/display/fonts.py        |       29 |        2 |        6 |        1 |     91% |     33-34 |
| src/nhl\_scoreboard/display/holiday.py      |      546 |        2 |      136 |        2 |     99% | 135, 1448 |
| src/nhl\_scoreboard/display/logos.py        |       86 |        9 |       22 |        1 |     89% |41, 91-95, 99-101 |
| src/nhl\_scoreboard/display/matrix.py       |       43 |        0 |        4 |        0 |    100% |           |
| src/nhl\_scoreboard/display/mirror.py       |      148 |        5 |       42 |        3 |     96% |98, 126, 176, 197, 217 |
| src/nhl\_scoreboard/display/renderer.py     |      716 |        3 |      260 |        9 |     99% |623-\>625, 762-\>764, 773-\>778, 1068, 1103, 1313-\>1342, 1328-\>1327, 1335, 1348-\>1350 |
| src/nhl\_scoreboard/display/teams.py        |       16 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/hostname.py             |       63 |        2 |       10 |        1 |     96% |57-\>60, 71-72 |
| src/nhl\_scoreboard/light\_sensor.py        |       38 |        0 |        2 |        0 |    100% |           |
| src/nhl\_scoreboard/network.py              |       11 |        2 |        0 |        0 |     82% |     25-26 |
| src/nhl\_scoreboard/nhl/\_\_init\_\_.py     |        3 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/nhl/api.py              |      122 |       14 |        8 |        0 |     89% |122-124, 167-169, 177-182, 233-234 |
| src/nhl\_scoreboard/nhl/models.py           |      515 |        4 |      122 |        2 |     99% |234-235, 391, 559 |
| src/nhl\_scoreboard/setup\_server.py        |      134 |        1 |       30 |        3 |     98% |405, 425-\>429, 429-\>exit |
| src/nhl\_scoreboard/updater.py              |      233 |       24 |       52 |        8 |     89% |105-106, 124, 133, 151-155, 159-164, 231-236, 240-246, 257, 324-\>326, 351-\>353, 373-\>376, 377, 381 |
| src/nhl\_scoreboard/wifi.py                 |      140 |      109 |       28 |        0 |     18% |73-75, 94-142, 154-165, 169-171, 176-179, 183-185, 193-195, 203-213, 217-224, 228-240, 250-254, 261-265, 276-288, 292-296 |
| src/nhl\_scoreboard/wifi\_join.py           |       86 |        7 |       10 |        0 |     93% |112-114, 117-118, 201-202 |
| **TOTAL**                                   | **6014** |  **321** | **1706** |   **96** | **94%** |           |


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