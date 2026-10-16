# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                        |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/nhl\_scoreboard/\_\_init\_\_.py         |        1 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/\_\_main\_\_.py         |       45 |        3 |       10 |        2 |     91% | 58-59, 82 |
| src/nhl\_scoreboard/admin\_server.py        |      595 |       37 |      174 |       11 |     94% |651-\>649, 653-654, 659, 778-779, 786-787, 795-796, 899, 905, 928-929, 1035-\>1037, 1079, 1115, 1145, 1148-\>1159, 1370-1371, 1393-1413, 1417-1420, 1469, 1522 |
| src/nhl\_scoreboard/app.py                  |     1217 |       53 |      464 |       28 |     95% |323-\>327, 462-463, 490-\>492, 594-\>606, 622-\>624, 625, 690-\>689, 693-\>692, 719-720, 854, 1145-1147, 1161, 1181-\>exit, 1228, 1250, 1267-\>1264, 1312, 1321, 1332-1338, 1422, 1491-1492, 1504, 1551, 1588-1590, 1605-1607, 1646-1648, 1693-1695, 1727-1728, 1750-1751, 1809-1810, 1881, 1893, 2062, 2099, 2112, 2203, 2252, 2254, 2266 |
| src/nhl\_scoreboard/april\_fools.py         |       24 |        2 |        0 |        0 |     92% |     51-54 |
| src/nhl\_scoreboard/audio.py                |      100 |        2 |       30 |        0 |     98% |  180, 187 |
| src/nhl\_scoreboard/brightness.py           |        9 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/button.py               |       56 |        1 |        6 |        0 |     98% |        51 |
| src/nhl\_scoreboard/config.py               |      327 |        4 |       62 |        1 |     99% |330-331, 714-715 |
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
| src/nhl\_scoreboard/setup\_server.py        |      134 |        1 |       30 |        3 |     98% |405, 425-\>429, 429-\>exit |
| src/nhl\_scoreboard/updater.py              |      215 |       24 |       48 |        8 |     88% |98-99, 117, 126, 144-148, 152-157, 197-202, 206-212, 223, 290-\>292, 311-\>313, 333-\>336, 337, 341 |
| src/nhl\_scoreboard/wifi.py                 |      140 |      109 |       28 |        0 |     18% |73-75, 94-142, 154-165, 169-171, 176-179, 183-185, 193-195, 203-213, 217-224, 228-240, 250-254, 261-265, 276-288, 292-296 |
| src/nhl\_scoreboard/wifi\_join.py           |       86 |        7 |       10 |        0 |     93% |112-114, 117-118, 201-202 |
| **TOTAL**                                   | **5055** |  **279** | **1384** |   **66** | **94%** |           |


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