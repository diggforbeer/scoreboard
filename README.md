# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/diggforbeer/scoreboard/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                        |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|-------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| src/nhl\_scoreboard/\_\_init\_\_.py         |        1 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/\_\_main\_\_.py         |       45 |        3 |       10 |        2 |     91% | 58-59, 82 |
| src/nhl\_scoreboard/admin\_server.py        |      465 |       34 |      122 |        9 |     93% |577-\>575, 579-580, 585, 681-682, 689-690, 764, 770, 785-786, 805-\>807, 849, 881, 1035-1036, 1049-1064, 1068-1071, 1117, 1169 |
| src/nhl\_scoreboard/app.py                  |      874 |       41 |      344 |       25 |     94% |230-\>234, 326-327, 354-\>356, 427-\>429, 430, 493-\>492, 496-\>495, 516-517, 643, 915-\>exit, 964, 972, 986, 1003-\>1000, 1047, 1058-1064, 1117, 1186-1187, 1195, 1229, 1266-1268, 1283-1285, 1324-1326, 1362-1364, 1396-1397, 1452, 1458, 1484-\>1486, 1486-\>1490, 1541-\>exit, 1548, 1627, 1629 |
| src/nhl\_scoreboard/audio.py                |       79 |        2 |       22 |        0 |     98% |  144, 151 |
| src/nhl\_scoreboard/brightness.py           |        9 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/button.py               |       56 |        1 |        6 |        0 |     98% |        51 |
| src/nhl\_scoreboard/config.py               |      259 |        4 |       36 |        1 |     98% |259-260, 570-571 |
| src/nhl\_scoreboard/demo.py                 |       41 |        0 |        2 |        0 |    100% |           |
| src/nhl\_scoreboard/display/\_\_init\_\_.py |        0 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/display/ascii.py        |       54 |        4 |        6 |        1 |     92% |24, 28, 55-56 |
| src/nhl\_scoreboard/display/fonts.py        |       29 |        2 |        6 |        1 |     91% |     33-34 |
| src/nhl\_scoreboard/display/logos.py        |       86 |        9 |       22 |        1 |     89% |41, 91-95, 99-101 |
| src/nhl\_scoreboard/display/matrix.py       |       43 |        0 |        4 |        0 |    100% |           |
| src/nhl\_scoreboard/display/renderer.py     |      403 |        0 |      114 |        1 |     99% | 425-\>427 |
| src/nhl\_scoreboard/display/teams.py        |        8 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/light\_sensor.py        |       38 |        0 |        2 |        0 |    100% |           |
| src/nhl\_scoreboard/nhl/\_\_init\_\_.py     |        3 |        0 |        0 |        0 |    100% |           |
| src/nhl\_scoreboard/nhl/api.py              |       95 |        8 |        6 |        0 |     92% |96-98, 125-127, 159-160 |
| src/nhl\_scoreboard/nhl/models.py           |      323 |        0 |       60 |        0 |    100% |           |
| src/nhl\_scoreboard/setup\_server.py        |       87 |        1 |       16 |        3 |     96% |209, 222-\>226, 226-\>exit |
| src/nhl\_scoreboard/updater.py              |      215 |       24 |       48 |        8 |     88% |98-99, 117, 126, 144-148, 152-157, 197-202, 206-212, 223, 290-\>292, 311-\>313, 333-\>336, 337, 341 |
| src/nhl\_scoreboard/wifi.py                 |      140 |      109 |       28 |        0 |     18% |73-75, 94-142, 154-165, 169-171, 176-179, 183-185, 193-195, 203-213, 217-224, 228-240, 250-254, 261-265, 276-288, 292-296 |
| src/nhl\_scoreboard/wifi\_join.py           |       86 |        7 |       10 |        0 |     93% |112-114, 117-118, 201-202 |
| **TOTAL**                                   | **3439** |  **249** |  **864** |   **52** | **92%** |           |


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