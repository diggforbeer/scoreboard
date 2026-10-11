# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                        |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/nhl\_scoreboard/\_\_init\_\_.py         |        1 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/\_\_main\_\_.py         |       45 |        3 |       10 |        2 |     91% | 58-59, 82 |
| src/nhl\_scoreboard/admin\_server.py        |      593 |       37 |      174 |       11 |     94% |645-\>643, 647-648, 653, 772-773, 780-781, 789-790, 891, 897, 920-921, 1026-\>1028, 1070, 1106, 1136, 1139-\>1150, 1359-1360, 1382-1402, 1406-1409, 1458, 1511 |
| src/nhl\_scoreboard/app.py                  |     1154 |       49 |      456 |       28 |     95% |266-\>270, 405-406, 433-\>435, 537-\>549, 565-\>567, 568, 633-\>632, 636-\>635, 662-663, 797, 1088-1090, 1104, 1124-\>exit, 1171, 1193, 1210-\>1207, 1255, 1264, 1275-1281, 1365, 1434-1435, 1447, 1494, 1531-1533, 1548-1550, 1589-1591, 1627-1629, 1661-1662, 1729, 1741, 1910, 1947, 1960, 2051, 2100, 2102, 2114 |
| src/nhl\_scoreboard/april\_fools.py         |       24 |        2 |        0 |        0 |     92% |     51-54 |
| src/nhl\_scoreboard/audio.py                |       86 |        2 |       28 |        1 |     97% |111-\>117, 155, 162 |
| src/nhl\_scoreboard/brightness.py           |        9 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/button.py               |       56 |        1 |        6 |        0 |     98% |        51 |
| src/nhl\_scoreboard/config.py               |      309 |        4 |       54 |        1 |     99% |296-297, 677-678 |
| src/nhl\_scoreboard/demo.py                 |       58 |        0 |        8 |        0 |    100% |           |
| src/nhl\_scoreboard/display/\_\_init\_\_.py |        0 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/display/ascii.py        |       54 |        2 |        6 |        1 |     95% |     55-56 |
| src/nhl\_scoreboard/display/fonts.py        |       29 |        2 |        6 |        1 |     91% |     33-34 |
| src/nhl\_scoreboard/display/holiday.py      |      546 |        2 |      136 |        2 |     99% | 133, 1446 |
| src/nhl\_scoreboard/display/logos.py        |       86 |        9 |       22 |        1 |     89% |41, 91-95, 99-101 |
| src/nhl\_scoreboard/display/matrix.py       |       43 |        0 |        4 |        0 |    100% |           |
| src/nhl\_scoreboard/display/renderer.py     |      621 |        4 |      214 |        7 |     99% |531, 538, 620-\>622, 759-\>761, 770-\>775, 953, 988 |
| src/nhl\_scoreboard/display/teams.py        |       16 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/light\_sensor.py        |       38 |        0 |        2 |        0 |    100% |           |
| src/nhl\_scoreboard/nhl/\_\_init\_\_.py     |        3 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/nhl/api.py              |      122 |       14 |        8 |        0 |     89% |122-124, 167-169, 177-182, 233-234 |
| src/nhl\_scoreboard/nhl/models.py           |      490 |        3 |      116 |        1 |     99% |234-235, 391 |
| src/nhl\_scoreboard/setup\_server.py        |       87 |        1 |       16 |        3 |     96% |209, 222-\>226, 226-\>exit |
| src/nhl\_scoreboard/updater.py              |      215 |       24 |       48 |        8 |     88% |98-99, 117, 126, 144-148, 152-157, 197-202, 206-212, 223, 290-\>292, 311-\>313, 333-\>336, 337, 341 |
| src/nhl\_scoreboard/wifi.py                 |      140 |      109 |       28 |        0 |     18% |73-75, 94-142, 154-165, 169-171, 176-179, 183-185, 193-195, 203-213, 217-224, 228-240, 250-254, 261-265, 276-288, 292-296 |
| src/nhl\_scoreboard/wifi\_join.py           |       86 |        7 |       10 |        0 |     93% |112-114, 117-118, 201-202 |
| **TOTAL**                                   | **4911** |  **275** | **1352** |   **67** | **94%** |           |


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