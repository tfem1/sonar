# sonar

Minimal system monitor for the Linux and Windows terminal.

![sonar](docs/tsunami.png)

## Install

You need Python 3.9 or newer.

**Linux**

```sh
curl -fsSL https://raw.githubusercontent.com/tfem1/sonar/main/install.sh | sh
```

**Windows** (PowerShell)

```powershell
irm https://raw.githubusercontent.com/tfem1/sonar/main/install.ps1 | iex
```

Then open a new terminal and type `sonar`.

<details><summary>Install with git, or uninstall</summary>

```sh
git clone https://github.com/tfem1/sonar
cd sonar
./install.sh                                          # Linux
powershell -ExecutionPolicy Bypass -File install.ps1  # Windows
```

Uninstall: `./install.sh --uninstall` or `install.ps1 -Uninstall`.
No git? Download the [ZIP](https://github.com/tfem1/sonar/archive/refs/heads/main.zip) and run the same script.

</details>

## Usage

```sh
sonar              # start
sonar -t volcano   # pick a theme
sonar -l           # list themes
```

| key | action |
|---|---|
| `↑` `↓` or `j` `k` | select a process |
| `x` | kill the selected process (asks y/n) |
| `/` | filter by name |
| `s` / `r` | change sort / reverse it |
| `t` | tree view |
| `u` | only my processes |
| `1` … `5` | show / hide a panel |
| `+` / `-` | refresh faster / slower |
| `p` | pause |
| `c` | choose a theme |
| `?` | help |
| `q` | quit |

| help `?` | filter `/` | tree `t` |
|---|---|---|
| ![help](docs/help.png) | ![filter](docs/filter.png) | ![tree](docs/tree.png) |

## Themes

50 themes. Press `c` to try them live, then `Enter` to keep one.

![theme picker](docs/picker.png)

| volcano | synthwave |
|---|---|
| ![volcano](docs/volcano.png) | ![synthwave](docs/synthwave.png) |
| **prism** | **aurora** |
| ![prism](docs/prism.png) | ![aurora](docs/aurora.png) |

Light themes for light terminals, here `sky`:

![sky](docs/sky.png)

## License

MIT
