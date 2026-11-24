# 材料科学依赖库参考

本文档记录 `/public/software/apps/sag-tool` 中已确认的材料科学、分子模拟、量子化学、后处理和运行依赖。生成计算脚本时必须优先使用这里列出的路径、环境脚本、可执行文件和数据目录。

## 判定规则

- 材料科学软件判断优先依据 `/public/software/apps/sag-tool` 下的软件目录、环境脚本和关键可执行文件。
- 除非本文档明确写出 modulefile，不要把 sag-tool 中的软件写成 `module load <software>`；多数软件应通过 `source <env.sh>` 加载环境。
- 生成脚本时应写绝对路径或先 `source` 对应 `env.sh`，再调用关键入口。
- 如果软件需要赝势、基组、势函数、数据集等外部数据，必须使用本文档列出的数据目录；未列出数据目录时，应要求用户提供，不能虚构路径。
- 当前已确认 VASP 安装目录中没有 POTCAR/POTPAW 数据目录；VASP 任务需要用户提供 `POTCAR` 或可访问的 POTCAR 来源。
- 当前已确认 Quantum ESPRESSO 安装目录中没有内置 pseudo/UPF 数据目录；QE 任务如可接受 SG15 ONCV PBE UPF，应直接使用兼容赝势目录 `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf`，否则需要用户提供 `.UPF` 赝势目录。
- ABACUS 已提供 SG15 UPF 赝势和数值原子轨道文件，可直接在 ABACUS 输入中引用；赝势目录为 `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf`，轨道目录为 `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15-Version1p0__StandardOrbitals-Version2p0`。
- CP2K 已提供完整 `app/data` 数据目录，脚本中应设置 `CP2K_DATA_DIR` 或使用 `env.sh` 已导出的变量。
- 未在本文档明确列出的软件、module、容器镜像、赝势库、基组库或势函数库，不要推断为已支持。

## 总体结构

```text
/public/software/apps/sag-tool
├── matsoft
│   ├── abacus/v3.9.0.2
│   ├── abinit/10.0.9-gcc930_openmpi415
│   ├── cp2k/v2024.2-intelmpi2021
│   ├── matstream/v1.0.0
│   ├── qe/7.0-intel2021
│   ├── qe-workflow/v1.0.0
│   └── vasp/5.4.4-intelmpi2017_optcell
├── mdsoft
│   ├── gromacs/2023.2-gcc930_intelmpi17_optv1
│   ├── lammps/5Nov16-intelmpi2017
│   └── lammps-workflow/v1.0.0
├── pysoftenv
│   └── pyscf/py310
├── qcsoft
│   ├── g16-hy
│   ├── orca/6.1.0-f.0
│   └── orca-workflow/v1.0.0
├── tools
│   ├── compiler
│   └── mpi
└── vaspkit
```

## 材料科学与模拟软件清单

| 软件 | 版本 | 软件路径 | 环境加载 | 关键入口 | 重要数据目录 | 判断 |
|---|---:|---|---|---|---|---|
| ABACUS | 3.9.0.2 | `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2` | `source /public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/env.sh` | `abacus`, `abacus-workflow`, `abacus2J.py`, `ase`, `phonopy`, `pmg` | UPF: `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf`; ORB: `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15-Version1p0__StandardOrbitals-Version2p0` | supported |
| ABINIT | 10.0.9 | `/public/software/apps/sag-tool/matsoft/abinit/10.0.9-gcc930_openmpi415` | `source /public/software/apps/sag-tool/matsoft/abinit/10.0.9-gcc930_openmpi415/env.sh` | `abinit`, `anaddb`, `cut3d`, `optic`, `mrgddb`, `multibinit` | 未发现内置赝势目录，需用户提供 | supported |
| CP2K | 2024.2 | `/public/software/apps/sag-tool/matsoft/cp2k/v2024.2-intelmpi2021` | `source /public/software/apps/sag-tool/matsoft/cp2k/v2024.2-intelmpi2021/env.sh` | `cp2k.psmp` | `/public/software/apps/sag-tool/matsoft/cp2k/v2024.2-intelmpi2021/app/data` | supported |
| Quantum ESPRESSO | 7.0 | `/public/software/apps/sag-tool/matsoft/qe/7.0-intel2021` | `source /public/software/apps/sag-tool/matsoft/qe/7.0-intel2021/env.sh` | `pw.x`, `ph.x`, `bands.x`, `dos.x`, `projwfc.x`, `neb.x`, `pp.x`, `q2r.x`, `matdyn.x` | 未发现内置 pseudo/UPF 目录；兼容 SG15 ONCV PBE UPF: `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf` | supported |
| QE workflow | 1.0.0 | `/public/software/apps/sag-tool/matsoft/qe-workflow/v1.0.0` | `source /public/software/apps/sag-tool/matsoft/qe-workflow/v1.0.0/env.sh` | Python 工作流环境，含 `qe_env` | `/public/software/apps/sag-tool/matsoft/qe-workflow/v1.0.0/qe_env/share/examples` | supported |
| VASP | 5.4.4 | `/public/software/apps/sag-tool/matsoft/vasp/5.4.4-intelmpi2017_optcell` | `source /public/software/apps/sag-tool/matsoft/vasp/5.4.4-intelmpi2017_optcell/env.sh` | `vasp_std`, `vasp_gam`, `vasp_ncl` | 未发现 POTCAR/POTPAW 目录，必须用户提供 `POTCAR` | supported |
| MatStream | 1.0.0 | `/public/software/apps/sag-tool/matsoft/matstream/v1.0.0` | `source /public/software/apps/sag-tool/matsoft/matstream/v1.0.0/env.sh` | `matstream`, `phonopy`, `pmg`, `ase` | 使用 VASP 结果和 Python 后处理库；未发现独立势库 | supported |
| LAMMPS | 5Nov16 | `/public/software/apps/sag-tool/mdsoft/lammps/5Nov16-intelmpi2017` | `source /public/software/apps/sag-tool/mdsoft/lammps/5Nov16-intelmpi2017/env.sh` | `lmp`, `lmp_intel_cpu_intelmpi` | 未发现通用势函数库，势函数文件需用户提供或由任务生成 | supported |
| LAMMPS workflow | 1.0.0 | `/public/software/apps/sag-tool/mdsoft/lammps-workflow/v1.0.0` | `source /public/software/apps/sag-tool/mdsoft/lammps-workflow/v1.0.0/env.sh` | Python 工作流环境，含 `ase` | `/public/software/apps/sag-tool/mdsoft/lammps-workflow/v1.0.0/lammps_env/share/examples` | supported |
| GROMACS | 2023.2 | `/public/software/apps/sag-tool/mdsoft/gromacs/2023.2-gcc930_intelmpi17_optv1` | `source /public/software/apps/sag-tool/mdsoft/gromacs/2023.2-gcc930_intelmpi17_optv1/env.sh` | `gmx_mpi`, `GMXRC` | GROMACS data prefix 为 `/public/software/apps/sag-tool/mdsoft/gromacs/2023.2-gcc930_intelmpi17_optv1/app` | supported |
| PySCF | py310 | `/public/software/apps/sag-tool/pysoftenv/pyscf/py310` | 直接调用 `/public/software/apps/sag-tool/pysoftenv/pyscf/py310/bin/python`，或激活该虚拟环境 | `python` | Python 包环境，无材料赝势库 | supported |
| ORCA | 6.1.0 | `/public/software/apps/sag-tool/qcsoft/orca/6.1.0-f.0` | `source /public/software/apps/sag-tool/qcsoft/orca/6.1.0-f.0/env.sh` | `orca`, `orca_run.sh`, `orca_plot`, `orca_vib`, `orca_md` | `/public/software/apps/sag-tool/qcsoft/orca/6.1.0-f.0/bin/datasets` | supported |
| ORCA workflow | 1.0.0 | `/public/software/apps/sag-tool/qcsoft/orca-workflow/v1.0.0` | `source /public/software/apps/sag-tool/qcsoft/orca-workflow/v1.0.0/env.sh` | Python 工作流环境，含 `ase` 等依赖 | 工作流 Python 环境，无独立量化数据目录 | supported |
| Gaussian 16 high-yield | container | `/public/software/apps/sag-tool/qcsoft/g16-hy` | 结合 Apptainer 或 `scripts/g16_run.sh`；`env.sh` 本身基本为空 | `g16-hy-root.sif`, `scripts/g16_run.sh` | 容器内数据，外部未暴露基组目录 | supported |
| VASPkit | unknown | `/public/software/apps/sag-tool/vaspkit` | 未发现 `env.sh` | 未发现可执行入口 | 未发现数据目录 | unknown |

## 关键数据目录

### ABACUS 赝势和轨道

```text
/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo
├── SG15_ONCV_v1.0_upf
└── SG15-Version1p0__StandardOrbitals-Version2p0
```

- `SG15_ONCV_v1.0_upf` 提供 `*_ONCV_PBE-1.0.upf` 文件，可用于 ABACUS，也可在 Quantum ESPRESSO 输入中作为 UPF 赝势来源。
- `SG15-Version1p0__StandardOrbitals-Version2p0` 提供 `*.orb` 数值原子轨道文件，ABACUS LCAO 任务需要在 `STRU` 中显式引用。
- ABACUS Python 环境中还可见同源资源镜像 `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/python3.10/site-packages/abacus_pseudopotentials/resources`；生成脚本时优先使用上面的稳定 `lib/pseudo` 路径。
- ABACUS 脚本可设置：

```bash
export ABACUS_PSEUDO_DIR=/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf
export ABACUS_ORBITAL_DIR=/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15-Version1p0__StandardOrbitals-Version2p0
```

### CP2K 数据目录

```text
/public/software/apps/sag-tool/matsoft/cp2k/v2024.2-intelmpi2021/app/data
```

关键文件包括：

```text
ALL_BASIS_SETS
ALL_POTENTIALS
BASIS_MOLOPT
GTH_BASIS_SETS
GTH_POTENTIALS
GTH_SOC_POTENTIALS
POTENTIAL
MM_POTENTIAL
dftd3.dat
vdW_kernel_table.dat
rVV10_kernel_table.dat
xTB_parameters
```

CP2K 输入中需要 `BASIS_SET_FILE_NAME`、`POTENTIAL_FILE_NAME` 或色散数据时，优先引用上述目录下文件。`env.sh` 已导出：

```bash
export CP2K_DATA_DIR=/public/software/apps/sag-tool/matsoft/cp2k/v2024.2-intelmpi2021/app/data
```

### ORCA 内置数据集

```text
/public/software/apps/sag-tool/qcsoft/orca/6.1.0-f.0/bin/datasets
├── DatasetsInfo/GMTKN55
└── Geometries/GMTKN55
```

ORCA 量子化学常规基组和 ECP 由 ORCA 程序自身处理；需要 benchmark 几何或 GMTKN55 数据时，可引用该 datasets 目录。

### 需要用户提供的数据

| 软件 | 缺失或未发现的数据 | 脚本生成要求 |
|---|---|---|
| VASP | `POTCAR`/POTPAW 数据目录 | 不要自动拼接 POTCAR 路径；脚本中检查工作目录是否已有 `POTCAR`，没有则提示用户提供。 |
| Quantum ESPRESSO | QE 安装目录未发现内置 pseudo/UPF；可用兼容 SG15 ONCV PBE UPF | 脚本中使用用户提供的 `pseudo_dir`；若任务允许 SG15 PBE，直接设置为 `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf`。 |
| ABINIT | 赝势目录 | 需要用户提供 ABINIT 兼容赝势文件路径。 |
| LAMMPS | 势函数库 | 需要用户提供 EAM/Tersoff/ReaxFF/MEAM 等势函数文件，或由上游流程生成。 |

## 典型脚本片段

### ABACUS

```bash
source /public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/env.sh
export ABACUS_PSEUDO_DIR=/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf
export ABACUS_ORBITAL_DIR=/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15-Version1p0__StandardOrbitals-Version2p0
mpirun -np "${SLURM_NTASKS:-4}" abacus
```

生成 ABACUS `STRU` 时，`ATOMIC_SPECIES` 的 UPF 文件应来自 `$ABACUS_PSEUDO_DIR`，`NUMERICAL_ORBITAL` 的 ORB 文件应来自 `$ABACUS_ORBITAL_DIR`。

### CP2K

```bash
source /public/software/apps/sag-tool/matsoft/cp2k/v2024.2-intelmpi2021/env.sh
export CP2K_DATA_DIR=/public/software/apps/sag-tool/matsoft/cp2k/v2024.2-intelmpi2021/app/data
mpirun -np "${SLURM_NTASKS:-4}" cp2k.psmp -i cp2k.inp -o cp2k.out
```

CP2K 输入中可使用：

```text
BASIS_SET_FILE_NAME  ${CP2K_DATA_DIR}/BASIS_MOLOPT
POTENTIAL_FILE_NAME  ${CP2K_DATA_DIR}/GTH_POTENTIALS
```

### Quantum ESPRESSO

```bash
source /public/software/apps/sag-tool/matsoft/qe/7.0-intel2021/env.sh
export QE_PSEUDO_DIR=/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf
mpirun -np "${SLURM_NTASKS:-4}" pw.x -in scf.in > scf.out
```

QE 安装目录未发现内置 pseudo 目录。生成 `scf.in` 时，`pseudo_dir` 必须指向用户提供目录；若计算方法允许 SG15 ONCV PBE UPF，可直接指向 `$QE_PSEUDO_DIR`，不要再让用户重新寻找兼容赝势库。

### VASP

```bash
source /public/software/apps/sag-tool/matsoft/vasp/5.4.4-intelmpi2017_optcell/env.sh
test -f POTCAR || { echo "POTCAR is required but not found"; exit 1; }
mpirun -np "${SLURM_NTASKS:-4}" vasp_std > vasp.out
```

选择入口时：

- 标准结构优化、静态、能带、态密度优先用 `vasp_std`。
- Gamma-only 大超胞可用 `vasp_gam`。
- 非共线、自旋轨道耦合任务用 `vasp_ncl`。

### LAMMPS

```bash
source /public/software/apps/sag-tool/mdsoft/lammps/5Nov16-intelmpi2017/env.sh
mpirun -np "${SLURM_NTASKS:-4}" lmp -in in.lammps
```

LAMMPS 版本较旧。论文依赖新 package、新 pair style 或新语法时，应标记为 `partial`，并在脚本中检查势函数文件是否存在。

### GROMACS

```bash
source /public/software/apps/sag-tool/mdsoft/gromacs/2023.2-gcc930_intelmpi17_optv1/env.sh
gmx_mpi grompp -f md.mdp -c conf.gro -p topol.top -o md.tpr
mpirun -np "${SLURM_NTASKS:-4}" gmx_mpi mdrun -deffnm md
```

### ORCA

```bash
source /public/software/apps/sag-tool/qcsoft/orca/6.1.0-f.0/env.sh
/public/software/apps/sag-tool/qcsoft/orca/6.1.0-f.0/bin/orca orca.inp > orca.out
```

ORCA MPI 并行通常由输入文件中的 `%pal nprocs ... end` 控制；脚本中优先使用 ORCA 的绝对路径。

### Gaussian 16 high-yield

```bash
source /public/software/apps/sag-tool/qcsoft/g16-hy/env.sh
/public/software/apps/sag-tool/qcsoft/g16-hy/scripts/g16_run.sh -t opt
```

`g16_run.sh` 期望当前目录下存在以任务名命名的子目录，并在子目录中找到 `g16.com`、`ts.com` 或 `irc.com` 等输入文件。

### PySCF

```bash
/public/software/apps/sag-tool/pysoftenv/pyscf/py310/bin/python run_pyscf.py
```

PySCF 适合分子量子化学、周期体系模型和后处理脚本；它不提供材料赝势库，输入脚本所需 basis/ECP 应由 PySCF 内置名称或用户文件给出。

## 编译器与 MPI 依赖

| 依赖 | 路径 | 主要用途 |
|---|---|---|
| Intel Compiler 2017.5.239 | `/public/software/apps/sag-tool/tools/compiler/intel-2017.5.239` | VASP、LAMMPS、MatStream 等 Intel 2017 构建软件。 |
| Intel oneAPI 2021.3.0 | `/public/software/apps/sag-tool/tools/compiler/2021.3.0` | QE、CP2K 等 oneAPI/MKL 运行库。 |
| GCC 9.3.0 | `/public/software/apps/sag-tool/tools/compiler/gcc-9.3.0` | ABINIT、GROMACS、ORCA workflow、Python 科学栈运行库。 |
| IntelMPI 2017.4.239 | `/public/software/apps/sag-tool/tools/mpi/intelmpi/2017.4.239` | VASP、LAMMPS、GROMACS 等并行运行。 |
| IntelMPI 2021.6.0 | `/public/software/apps/sag-tool/tools/mpi/intelmpi/2021.6.0` | QE、CP2K 等并行运行。 |
| OpenMPI 4.1.5 | `/public/software/apps/sag-tool/tools/mpi/openmpi/openmpi-4.1.5` | ABINIT 等 OpenMPI 构建软件。 |
| HPCX/UCX/PMIX | `/public/software/apps/sag-tool/tools/mpi/hpcx/v2.11.0`, `/public/software/apps/sag-tool/tools/mpi/pmix` | ABINIT OpenMPI 运行依赖。 |

通常不需要在用户脚本中手动加载这些底层依赖；优先 `source` 软件自身 `env.sh`，因为环境脚本已设置编译器、MPI、MKL、PATH 和 LD_LIBRARY_PATH。

## 论文任务到依赖的匹配表

| 任务类型 | 支持状态 | 推荐依赖 | 注意事项 |
|---|---|---|---|
| 第一性原理 DFT 结构优化 | supported | VASP, Quantum ESPRESSO, ABACUS, ABINIT, CP2K | VASP/ABINIT 需要外部赝势；QE 自身无内置 pseudo，但可使用 ABACUS SG15 ONCV PBE UPF 兼容目录；ABACUS/CP2K 有可用数据目录。 |
| 静态能量、能带、态密度 | supported | VASP, QE, ABACUS, ABINIT, CP2K | QE 后处理入口包括 `bands.x`, `dos.x`, `projwfc.x`, `pp.x`。 |
| 声子与热力学 | supported | QE `ph.x/q2r.x/matdyn.x`, ABINIT `anaddb`, ABACUS/MatStream `phonopy` | 需要保证前序力常数或位移计算文件完整。 |
| NEB/扩散路径 | supported | QE `neb.x`, VASP | VASP 仍需用户提供 `POTCAR`。 |
| 分子动力学 | supported | LAMMPS, GROMACS, CP2K | LAMMPS/GROMACS 势场和拓扑文件通常需用户提供。 |
| 机器学习势或力场计算 | partial | CP2K data 中有 `DeePMD`, `NequIP`, `Allegro`, `NNP` 目录；LAMMPS 需额外势文件 | 具体模型文件需用户提供。 |
| 量子化学 DFT/TDDFT/频率 | supported | ORCA, Gaussian 16 container, PySCF, CP2K | ORCA/Gaussian 输入文件由任务生成；PySCF 用 Python 脚本。 |
| VASP 后处理 | supported | MatStream, pymatgen, ASE, phonopy | VASPkit 未确认可执行入口，不应作为默认工具。 |
| 自动化工作流 | supported | MatStream, QE workflow, LAMMPS workflow, ORCA workflow | workflow 环境多为 Python 依赖，实际求解器仍需加载对应软件环境。 |

## 依赖判断建议

1. 论文明确使用 ABACUS 时，匹配 `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2`，并优先使用已安装的 SG15 UPF 与 ORB 目录。
2. 论文明确使用 CP2K 时，匹配 `/public/software/apps/sag-tool/matsoft/cp2k/v2024.2-intelmpi2021`，并在脚本或输入文件中引用 `CP2K_DATA_DIR`。
3. 论文明确使用 Quantum ESPRESSO 时，匹配 `/public/software/apps/sag-tool/matsoft/qe/7.0-intel2021`；若任务采用 PBE 且可接受 SG15 ONCV UPF，直接使用 `/public/software/apps/sag-tool/matsoft/abacus/v3.9.0.2/lib/pseudo/SG15_ONCV_v1.0_upf`；若论文要求其他赝势族或泛函，则需要用户提供对应 pseudo 目录。
4. 论文明确使用 VASP 时，匹配 `/public/software/apps/sag-tool/matsoft/vasp/5.4.4-intelmpi2017_optcell`；必须检查 `POTCAR`。
5. 论文明确使用 LAMMPS 时，匹配 `/public/software/apps/sag-tool/mdsoft/lammps/5Nov16-intelmpi2017`；若依赖新语法或新 package，标记为 `partial`。
6. 论文明确使用 GROMACS 时，匹配 `/public/software/apps/sag-tool/mdsoft/gromacs/2023.2-gcc930_intelmpi17_optv1`。
7. 论文明确使用 ORCA 时，匹配 `/public/software/apps/sag-tool/qcsoft/orca/6.1.0-f.0`，脚本优先使用 ORCA 绝对路径。
8. 论文明确使用 Gaussian 16 时，匹配 `/public/software/apps/sag-tool/qcsoft/g16-hy/g16-hy-root.sif` 和 `scripts/g16_run.sh`。
9. 论文需要 Python 材料后处理、结构生成、声子或工作流时，可匹配 MatStream、QE workflow、LAMMPS workflow、ORCA workflow、PySCF、ASE、pymatgen、phonopy。
10. 遇到 VASPkit 时，只能判断为 `unknown`，因为目录存在但未发现环境脚本和可执行入口。
