# 材料科学依赖库参考

本文档记录 `/public/software/apps/sag-tool` 中已确认的材料科学、分子模拟、量子化学、后处理和运行依赖。生成计算脚本时必须优先使用这里列出的路径、环境脚本、可执行文件和数据目录。

## 快照信息

- 探查根目录：`/public/software/apps/sag-tool`
- 当前根目录权限为 `drwxr-xr-x root root`；任务应将输入和输出放在用户工作区，不要写入 sag-tool。

## 判定规则

- `path-confirmed`：当前远程枚举明确返回安装目录、文件或容器镜像，但尚未完成命令版本或算例测试。
- `supported`：关键入口和必要资源均明确，且没有已知阻断项。
- `partial`：软件目录或部分入口存在，但环境脚本、求解器、数据资源、许可证或运行方式仍需确认。
- `unsupported`：当前 sag-tool 主目录枚举没有出现所需软件目录或关键入口。
- `unknown`：只有名称相近目录，或信息不足以判断软件、版本和能力。
- sag-tool 软件优先通过各版本目录的 `env.sh` 加载；只有远程确认存在环境脚本后，才能在正式任务中直接引用。
- 同一软件存在多个副本时，先检查 `env.sh`、关键入口及版本，再执行最小测试。
- `/public/software/apps/sag-tool/backup_20260727` 是备份目录，不作为默认运行环境。
- `/public/software/apps/sag-tool/sidereus-ai/home` 是用户/服务工作区，不作为公共材料软件依赖来源。
- 当前已确认 Quantum ESPRESSO 安装目录中没有内置 pseudo/UPF 数据目录；QE 任务如可接受 SG15 ONCV PBE UPF，应直接使用兼容赝势目录 `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf`，否则需要用户提供 `.UPF` 赝势目录。
- ABACUS 已提供 SG15 UPF 赝势和数值原子轨道文件，可直接在 ABACUS 输入中引用；赝势目录为 `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf`，轨道目录为 `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15-Version1p0__StandardOrbitals-Version2p0`。
- CP2K 已提供完整 `app/data` 数据目录，脚本中应设置 `CP2K_DATA_DIR` 或使用 `env.sh` 已导出的变量。
- 未记录的软件、Python 包、赝势、基组、势函数、力场或数据库不能推断为已安装。

## 当前总体结构

```text
/public/software/apps/sag-tool
├── bin
│   └── apptainer
├── etc/apptainer
├── matsoft
│   ├── abacus
│   │   ├── abacus.sif
│   │   └── v3.9.0.2
│   ├── matstream/v1.0.0
│   ├── qe/7.0-intel2021
│   ├── qe-workflow/v1.0.0
│   └── vasp
│       ├── 5.4.4-intelmpi2017_optcell
│       ├── 5.4.4-ioptcell_intelmpi2017_hdf5_libxc
│       └── matstream
├── mdsoft
│   ├── lammps/5Nov16-intelmpi2017
│   └── lammps-workflow/v1.0.0
├── qcsoft
│   ├── 6.1.0-f.0
│   ├── g16-hy
│   ├── gaussian-workflow/v1.0.0
│   ├── orca/6.1.0-f.0
│   └── orca-workflow/v1.0.0
├── qe/7.0-intel2021
├── vasp
│   ├── 5.4.4-ioptcell_intelmpi2017_hdf5_libxc
│   └── matstream/matstream.sif
├── vaspkit/1.5.1-none
└── tools
    ├── compiler
    │   ├── 2021.3.0
    │   ├── gcc-9.3.0
    │   └── intel-2017.5.239
    └── mpi
        ├── hpcx
        ├── intelmpi
        ├── openmpi
        └── pmix
```

当前 sag-tool 中还存在 `industry`、`biomni`、`aitool`、`gridview`、`sidereus-ai` 等目录，它们不属于本材料依赖说明的核心范围。

## 当前材料软件清单

| 软件 | 当前确认版本/形式 | 当前确认路径 | 已确认内容 | 判断 |
| --- | --- | --- | --- | --- |
| ABACUS | 3.9.0.2 | `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2` | 版本目录存在；另有 `matsoft/abacus/abacus.sif` | partial |
| Quantum ESPRESSO | 7.0 Intel 2021 | `/public/software/apps/sag-tool/matsoft/qe/7.0-intel2021` | 版本目录存在 | partial |
| Quantum ESPRESSO 副本 | 7.0 Intel 2021 | `/public/software/apps/sag-tool/qe/7.0-intel2021` | `app`、`case`、`scripts`、`install.log` 存在 | partial |
| QE workflow | 1.0.0 | `/public/software/apps/sag-tool/matsoft/qe-workflow/v1.0.0` | 工作流版本目录存在 | partial |
| VASP | 5.4.4 IntelMPI 2017 optcell | `/public/software/apps/sag-tool/matsoft/vasp/5.4.4-intelmpi2017_optcell` | 版本目录存在 | partial |
| VASP | 5.4.4 IntelMPI 2017 HDF5/libxc | `/public/software/apps/sag-tool/matsoft/vasp/5.4.4-ioptcell_intelmpi2017_hdf5_libxc` | 版本目录存在 | partial |
| VASP 副本 | 5.4.4 IntelMPI 2017 HDF5/libxc | `/public/software/apps/sag-tool/vasp/5.4.4-ioptcell_intelmpi2017_hdf5_libxc` | `app`、`case`、`scripts`、`install.log` 存在 | partial |
| MatStream | 1.0.0 | `/public/software/apps/sag-tool/matsoft/matstream/v1.0.0` | 版本目录与 `.tgz` 包存在 | partial |
| MatStream 容器 | SIF | `/public/software/apps/sag-tool/vasp/matstream/matstream.sif` | 镜像文件存在 | partial |
| LAMMPS | 5Nov16 IntelMPI 2017 | `/public/software/apps/sag-tool/mdsoft/lammps/5Nov16-intelmpi2017` | 版本目录存在 | partial |
| LAMMPS workflow | 1.0.0 | `/public/software/apps/sag-tool/mdsoft/lammps-workflow/v1.0.0` | 工作流版本目录存在 | partial |
| ORCA | 6.1.0-f.0 | `/public/software/apps/sag-tool/qcsoft/orca/6.1.0-f.0` | 版本目录存在 | partial |
| ORCA 副本 | 6.1.0-f.0 | `/public/software/apps/sag-tool/qcsoft/6.1.0-f.0` | `bin`、`lib`、`external`、`env.sh`、`orca_run.sh` 存在 | path-confirmed |
| ORCA workflow | 1.0.0 | `/public/software/apps/sag-tool/qcsoft/orca-workflow/v1.0.0` | 工作流版本目录存在 | partial |
| Gaussian 16 high-yield | SIF | `/public/software/apps/sag-tool/qcsoft/g16-hy/g16-hy-root.sif` | 镜像和 `scripts` 目录存在 | partial |
| Gaussian workflow | 1.0.0 | `/public/software/apps/sag-tool/qcsoft/gaussian-workflow/v1.0.0` | 工作流版本目录存在 | partial |
| VASPkit | 1.5.1 | `/public/software/apps/sag-tool/vaspkit/1.5.1-none` | `app`、`case`、`scripts`、`source`、`install.log` 存在 | partial |
| Apptainer | 直接入口 | `/public/software/apps/sag-tool/bin/apptainer` | 二进制文件和配置目录存在 | path-confirmed |

本次当前目录枚举没有发现以下旧软件目录：

```text
/public/software/apps/sag-tool/matsoft/abinit
/public/software/apps/sag-tool/matsoft/cp2k
/public/software/apps/sag-tool/mdsoft/gromacs
/public/software/apps/sag-tool/pysoftenv
```

因此 ABINIT、CP2K、GROMACS、PySCF 和依赖 `pysoftenv` 的 PyATB/MLIP Python 环境，在本快照中不能判断为已支持。仓库内其他说明或技能即使记录了这些路径，也必须以当前远程文件系统为准。

## 软件入口与加载建议

### ABACUS

当前已确认：

```text
/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2
/public/software/apps/sag-tool/matsoft/abacus/abacus.sif
```

在完成入口检查前，ABACUS 任务应判断为 `partial`：

```bash
ABACUS_ROOT=/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2
test -f "$ABACUS_ROOT/env.sh" || { echo "ABACUS env.sh not confirmed" >&2; exit 1; }
source "$ABACUS_ROOT/env.sh"
command -v abacus || { echo "ABACUS executable unavailable" >&2; exit 1; }
abacus --version
```

容器候选调用：

```bash
APPTAINER=/public/software/apps/sag-tool/bin/apptainer
IMAGE=/public/software/apps/sag-tool/matsoft/abacus/abacus.sif
test -x "$APPTAINER" && test -r "$IMAGE" || exit 1
"$APPTAINER" exec "$IMAGE" abacus --version
```

### Quantum ESPRESSO

当前存在两个 QE 7.0 目录：

```text
/public/software/apps/sag-tool/matsoft/qe/7.0-intel2021
/public/software/apps/sag-tool/qe/7.0-intel2021
```

第二个目录明确包含 `app`、`case`、`scripts` 和 `install.log`。正式脚本应先确认哪个目录包含有效 `env.sh` 和 `pw.x`，不要同时加载两个副本。

候选检查：

```bash
for QE_ROOT in \
  /public/software/apps/sag-tool/matsoft/qe/7.0-intel2021 \
  /public/software/apps/sag-tool/qe/7.0-intel2021
do
  if test -f "$QE_ROOT/env.sh"; then
    source "$QE_ROOT/env.sh"
    command -v pw.x && pw.x -help >/dev/null
    break
  fi
done
```

`ph.x`、`bands.x`、`dos.x`、`projwfc.x`、`neb.x`、`pp.x`、`q2r.x` 和 `matdyn.x` 必须逐项确认。

### VASP

当前存在三个 VASP 5.4.4 候选目录：

```text
/public/software/apps/sag-tool/matsoft/vasp/5.4.4-intelmpi2017_optcell
/public/software/apps/sag-tool/matsoft/vasp/5.4.4-ioptcell_intelmpi2017_hdf5_libxc
/public/software/apps/sag-tool/vasp/5.4.4-ioptcell_intelmpi2017_hdf5_libxc
```

第三个目录明确包含 `app`、`case`、`scripts` 和 `install.log`。使用前确认所选目录中的 `env.sh` 以及 `vasp_std`、`vasp_gam`、`vasp_ncl`。

```bash
VASP_ROOT=/public/software/apps/sag-tool/matsoft/vasp/5.4.4-intelmpi2017_optcell
test -f "$VASP_ROOT/env.sh" || { echo "VASP env.sh not confirmed" >&2; exit 1; }
source "$VASP_ROOT/env.sh"
command -v vasp_std || { echo "vasp_std unavailable" >&2; exit 1; }
test -f POTCAR || { echo "POTCAR is required" >&2; exit 1; }
```

当前探查没有确认 POTCAR/POTPAW 数据目录。即使 VASP 二进制可用，也必须由用户提供合法可访问的 `POTCAR`。

### LAMMPS

当前版本目录：

```text
/public/software/apps/sag-tool/mdsoft/lammps/5Nov16-intelmpi2017
```

候选加载检查：

```bash
LAMMPS_ROOT=/public/software/apps/sag-tool/mdsoft/lammps/5Nov16-intelmpi2017
test -f "$LAMMPS_ROOT/env.sh" || { echo "LAMMPS env.sh not confirmed" >&2; exit 1; }
source "$LAMMPS_ROOT/env.sh"
command -v lmp || command -v lmp_intel_cpu_intelmpi || exit 1
```

版本 `5Nov16` 较旧。依赖新 pair style、fix、package 或输入语法的论文流程应保持 `partial`。当前未确认通用 EAM、Tersoff、ReaxFF 或 MEAM 势函数库。

### ORCA

当前存在两个 ORCA 6.1.0-f.0 目录：

```text
/public/software/apps/sag-tool/qcsoft/orca/6.1.0-f.0
/public/software/apps/sag-tool/qcsoft/6.1.0-f.0
```

第二个目录已明确确认包含 `bin`、`lib`、`external`、`env.sh` 和 `orca_run.sh`。在没有进一步差异比较前，优先探测这个结构完整的路径：

```bash
ORCA_ROOT=/public/software/apps/sag-tool/qcsoft/6.1.0-f.0
source "$ORCA_ROOT/env.sh"
test -x "$ORCA_ROOT/bin/orca" || { echo "ORCA executable not confirmed" >&2; exit 1; }
"$ORCA_ROOT/bin/orca" --version
```

ORCA 并行通常由输入中的 `%pal nprocs ... end` 控制，不要用任意系统 MPI 强行启动 ORCA。

### Gaussian 16

当前确认：

```text
/public/software/apps/sag-tool/qcsoft/g16-hy/g16-hy-root.sif
/public/software/apps/sag-tool/qcsoft/g16-hy/scripts
/public/software/apps/sag-tool/qcsoft/gaussian-workflow/v1.0.0
/public/software/apps/sag-tool/bin/apptainer
```

运行前查看容器 runscript，不要猜测镜像内入口：

```bash
APPTAINER=/public/software/apps/sag-tool/bin/apptainer
IMAGE=/public/software/apps/sag-tool/qcsoft/g16-hy/g16-hy-root.sif
"$APPTAINER" inspect --runscript "$IMAGE"
```

Gaussian 许可证、容器内命令和输入输出约定尚未完成运行验证，因此判断为 `partial`。

### VASPkit

当前明确存在 1.5.1 版本目录：

```text
/public/software/apps/sag-tool/vaspkit/1.5.1-none
├── app
├── case
├── scripts
├── source
└── install.log
```

与旧说明不同，不能再简单写成“只有 vaspkit 上级目录”。但本次尚未确认二进制确切路径：

```bash
VASPKIT_ROOT=/public/software/apps/sag-tool/vaspkit/1.5.1-none
find "$VASPKIT_ROOT/app" -maxdepth 3 -type f -name vaspkit -perm -u+x -print
```

找到唯一入口并完成帮助或最小 VASP 输出测试后，才能从 `partial` 提升为 `supported`。

### MatStream 与工作流环境

当前确认：

```text
/public/software/apps/sag-tool/matsoft/matstream/v1.0.0
/public/software/apps/sag-tool/vasp/matstream/matstream.sif
/public/software/apps/sag-tool/matsoft/qe-workflow/v1.0.0
/public/software/apps/sag-tool/mdsoft/lammps-workflow/v1.0.0
/public/software/apps/sag-tool/qcsoft/orca-workflow/v1.0.0
/public/software/apps/sag-tool/qcsoft/gaussian-workflow/v1.0.0
```

这些目录证明封装环境存在，但不证明内部 solver、Python 包和固定路径仍与当前安装一致。运行前需检查各自 `env.sh`、Python 入口、帮助、示例目录和实际 solver 路径。

## 关键材料数据资源

### ABACUS SG15 资源候选

当前 ABACUS 3.9.0.2 版本目录已确认存在。仓库现有技能引用以下目录，但本快照尚未完成这些深层路径的当前文件枚举：

```text
/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf
/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15-Version1p0__StandardOrbitals-Version2p0
```

使用前必须执行：

```bash
PSEUDO=/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf
ORBITAL=/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15-Version1p0__StandardOrbitals-Version2p0
test -d "$PSEUDO" && test -n "$(find "$PSEUDO" -maxdepth 1 -name '*.upf' -print -quit)" || exit 1
test -d "$ORBITAL" && test -n "$(find "$ORBITAL" -maxdepth 1 -name '*.orb' -print -quit)" || exit 1
```

只有检查通过后，ABACUS 或兼容 PBE/SG15 的 QE 任务才能使用这些目录。

### 当前未确认的数据

| 软件 | 当前缺口 | 脚本要求 |
| --- | --- | --- |
| VASP | 未确认 POTCAR/POTPAW | 要求用户提供 `POTCAR`，运行前 `test -f POTCAR` |
| Quantum ESPRESSO | 未确认安装内置 pseudo/UPF | 使用用户提供的 `pseudo_dir`；ABACUS SG15 候选目录需先验证 |
| ABACUS | SG15 UPF/ORB 深层文件尚待本轮复核 | 逐项检查 `.upf` 与 `.orb` 文件 |
| LAMMPS | 未确认势函数库 | 用户提供 EAM/Tersoff/ReaxFF/MEAM 势文件 |
| Gaussian | 镜像内基组与许可证未运行验证 | 检查容器入口与授权状态 |
| ORCA | 数据集/基组目录未完成深层枚举 | 常规内置基组需通过最小作业验证 |

## 编译器、MPI 与容器运行时

| 依赖 | 当前确认路径 | 用途 | 判断 |
| --- | --- | --- | --- |
| Intel 2017 | `/public/software/apps/sag-tool/tools/compiler/intel-2017.5.239` | VASP、LAMMPS 等旧 Intel 构建 | path-confirmed |
| oneAPI 2021 | `/public/software/apps/sag-tool/tools/compiler/2021.3.0` | QE 等 Intel 2021 构建 | path-confirmed |
| GCC 9.3.0 | `/public/software/apps/sag-tool/tools/compiler/gcc-9.3.0` | GCC 构建的软件与工作流 | path-confirmed |
| IntelMPI 根目录 | `/public/software/apps/sag-tool/tools/mpi/intelmpi` | Intel 构建软件 MPI | path-confirmed |
| OpenMPI 根目录 | `/public/software/apps/sag-tool/tools/mpi/openmpi` | GCC/OpenMPI 构建软件 | path-confirmed |
| HPC-X 根目录 | `/public/software/apps/sag-tool/tools/mpi/hpcx` | HPC-X/UCX 通信栈 | path-confirmed |
| PMIx 根目录 | `/public/software/apps/sag-tool/tools/mpi/pmix` | MPI 进程管理依赖 | path-confirmed |
| Apptainer | `/public/software/apps/sag-tool/bin/apptainer` | 运行 ABACUS、Gaussian、MatStream SIF | path-confirmed |
| Apptainer 配置 | `/public/software/apps/sag-tool/etc/apptainer` | 容器运行配置 | path-confirmed |

优先加载软件自己的 `env.sh`，让它选择匹配的编译器和 MPI。不要在 VASP、QE、LAMMPS 或 ORCA 脚本中随意调用系统 `mpirun`。

## 典型任务到依赖的匹配

| 论文任务类型 | 当前判断 | 候选依赖 | 关键限制 |
| --- | --- | --- | --- |
| DFT 结构优化 | partial | ABACUS 3.9.0.2、QE 7.0、VASP 5.4.4 | 求解器入口和赝势/POTCAR需进一步确认 |
| 静态能量、能带、态密度 | partial | ABACUS、QE、VASP | QE 后处理入口、VASPkit 入口尚待确认 |
| 声子与热力学 | partial | QE、MatStream | `ph.x`、`q2r.x`、`matdyn.x`、phonopy 入口待确认 |
| NEB/扩散路径 | partial | QE、VASP | `neb.x` 与 VASP 入口待确认；VASP 需要 POTCAR |
| 经典分子动力学 | partial | LAMMPS 5Nov16 | 软件较旧，势函数必须外部提供 |
| VASP 后处理 | partial | VASPkit 1.5.1、MatStream | 二进制/环境入口尚待确认 |
| 量子化学 DFT/频率 | partial | ORCA 6.1.0、Gaussian SIF | ORCA 副本选择、Gaussian 运行时和授权需验证 |
| 自动化工作流 | partial | QE/LAMMPS/ORCA/Gaussian workflow、MatStream | 内部固定路径与 solver 需复核 |
| 容器化材料计算 | partial | Apptainer、ABACUS/Gaussian/MatStream SIF | 需验证执行位、runscript 和绑定目录 |
| ABINIT 计算 | unsupported | 当前主目录未发现 | 不能沿用旧路径 |
| CP2K 计算 | unsupported | 当前主目录未发现 | 不能沿用旧路径或 CP2K data |
| GROMACS 分子动力学 | unsupported | 当前主目录未发现 | GROMACS 与力场目录均未确认 |
| PySCF/PyATB | unsupported | 当前未发现 `pysoftenv` | Python 环境和包均未确认 |
| 机器学习势/MLIP | unknown | 未发现明确公共环境 | 框架、模型与 Python 环境需另行探查 |

## 已知缺口与风险

1. 同一软件存在多个安装副本：QE、VASP 和 ORCA 都不能仅凭目录名确定默认版本。
2. 当前完成了主目录结构枚举；关键二进制、`env.sh` 内容和最小算例尚未全部验证。
3. 旧依赖说明中的 ABINIT、CP2K、GROMACS 和 PySCF 目录没有出现在当前 sag-tool 主目录枚举中，不能继续报告为 supported。
4. VASPkit 1.5.1 目录当前存在，但二进制入口尚未确认。
5. ABACUS SG15 UPF/ORB 路径有仓库技能引用，但本轮没有完成远程深层文件核验，使用前必须检查。
6. VASP POTCAR、LAMMPS 势函数和 QE 赝势没有当前已确认的公共数据目录。
7. LAMMPS `5Nov16` 很旧；新语法或新 package 的论文流程可能不兼容。
8. ORCA 不应使用任意系统 MPI 启动；Gaussian 还需确认容器内入口和授权。
9. `backup_20260727` 中的历史软件不能作为活动公共依赖路径。
10. 不要修改 `/public/software/apps/sag-tool` 下的安装、环境、符号链接、镜像或配置。

## 依赖判断建议

1. 材料任务先从“当前材料软件清单”选择候选安装，再验证对应 `env.sh` 和关键入口。
2. 同一软件有多个副本时，比较 `readlink -f`、`env.sh`、二进制版本和最小测试结果后只选一个。
3. ABACUS、QE、VASP、LAMMPS、ORCA、Gaussian 和 VASPkit 在完成入口验证前统一保持 `partial`。
4. VASP 必须检查 `POTCAR`；LAMMPS 必须检查势函数；QE/ABACUS 必须检查实际赝势或轨道文件。
5. 当前未出现的 ABINIT、CP2K、GROMACS 和 PySCF 不得从旧依赖说明或其他集群配置补齐。
6. 优先使用软件自身 `env.sh`，不要手工混合 IntelMPI、OpenMPI、HPC-X 或不同编译器运行库。
7. 容器任务同时检查 `/public/software/apps/sag-tool/bin/apptainer`、镜像可读性、runscript 和输入目录绑定。
8. 未记录或未验证的材料依赖统一标记为 `unknown`，并列出需要补充的最小检查项。
