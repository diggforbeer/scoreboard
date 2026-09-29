# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                        |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/nhl\_scoreboard/\_\_init\_\_.py         |        1 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/\_\_main\_\_.py         |       45 |        3 |       10 |        2 |     91% | 58-59, 82 |
| src/nhl\_scoreboard/app.py                  |      780 |       31 |      312 |       23 |     95% |213-\>217, 295-296, 304-\>306, 377-\>379, 380, 443-\>442, 446-\>445, 466-467, 539, 811-\>exit, 860, 868, 882, 899-\>896, 943, 979, 1006, 1043-1045, 1060-1062, 1101-1103, 1139-1141, 1173-1174, 1229, 1235, 1261-\>1263, 1263-\>1267, 1318-\>exit, 1325, 1395, 1397 |
| src/nhl\_scoreboard/audio.py                |       55 |        1 |       16 |        0 |     99% |        92 |
| src/nhl\_scoreboard/brightness.py           |        9 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/button.py               |       56 |        1 |        6 |        0 |     98% |        51 |
| src/nhl\_scoreboard/config.py               |      256 |        4 |       36 |        1 |     98% |249-250, 550-551 |
| src/nhl\_scoreboard/demo.py                 |       40 |        0 |        2 |        0 |    100% |           |
| src/nhl\_scoreboard/display/\_\_init\_\_.py |        0 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/display/ascii.py        |       54 |        4 |        6 |        1 |     92% |24, 28, 55-56 |
| src/nhl\_scoreboard/display/fonts.py        |       29 |        2 |        6 |        1 |     91% |     33-34 |
| src/nhl\_scoreboard/display/logos.py        |       86 |        9 |       22 |        1 |     89% |41, 91-95, 99-101 |
| src/nhl\_scoreboard/display/matrix.py       |       43 |        0 |        4 |        0 |    100% |           |
| src/nhl\_scoreboard/display/renderer.py     |      330 |        0 |       90 |        1 |     99% | 418-\>420 |
| src/nhl\_scoreboard/display/teams.py        |        8 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/light\_sensor.py        |       38 |        0 |        2 |        0 |    100% |           |
| src/nhl\_scoreboard/nhl/\_\_init\_\_.py     |        3 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/nhl/api.py              |       86 |        8 |        4 |        0 |     91% |94-96, 108-110, 134-135 |
| src/nhl\_scoreboard/nhl/models.py           |      248 |        0 |       52 |        0 |    100% |           |
| src/nhl\_scoreboard/setup\_server.py        |       87 |        1 |       16 |        3 |     96% |207, 220-\>224, 224-\>exit |
| src/nhl\_scoreboard/status\_server.py       |      372 |       30 |      106 |        7 |     92% |323-325, 327-328, 331-333, 651, 653, 656, 711, 775-776, 788-800, 814-815, 912-913, 980-981, 982-\>984, 995, 1008-1011 |
| src/nhl\_scoreboard/updater.py              |      197 |       24 |       38 |        6 |     87% |94-95, 113, 122, 140-144, 148-153, 193-198, 202-208, 219, 309-\>312, 313, 317 |
| src/nhl\_scoreboard/wifi.py                 |      140 |      109 |       28 |        0 |     18% |73-75, 94-142, 154-165, 169-171, 176-179, 183-185, 193-195, 203-213, 217-224, 228-240, 250-254, 261-265, 276-288, 292-296 |
| src/nhl\_scoreboard/wifi\_join.py           |       86 |        7 |       10 |        0 |     93% |112-114, 117-118, 201-202 |
| **TOTAL**                                   | **3049** |  **234** |  **766** |   **46** | **92%** |           |


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