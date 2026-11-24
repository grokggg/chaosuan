# VersionHub 生物信息依赖库参考

本文档记录 `/public/software/VersionHub` 的依赖结构、可用环境、命令行软件、R 包能力和任务匹配建议，用于 `literature_workflow` 在拆解论文计算任务后判断当前环境是否支持对应依赖。

## 快照信息与判定规则

- 探查根目录：`/public/software/VersionHub`
- 生物信息主目录：`/public/software/VersionHub/biosoft`
- 文档中的“路径已确认”表示远程目录枚举明确返回该文件、目录或符号链接；不等价于已完成真实数据运行测试。
- 只有目录但没有确认命令入口、包元数据或容器运行时的依赖，应判断为 `partial` 或 `unknown`，不能仅凭名称判断为完全支持。
- 生成脚本时优先使用本文档中的绝对路径，或显式把 `biosoft/bin` 加入 `PATH`；不要假定登录 shell 已预加载 VersionHub。
- 参考数据库只确认到目录层级。具体物种、版本、索引格式和文件完整性必须在运行前继续检查。
- 未在本文档列出的软件、R 包、Python 包、数据库或版本，不应推断为已安装。

## 总体结构

```text
/public/software/VersionHub
├── R
│   ├── 3.6.3 ... 4.5.2
│   └── 4.4.2
│       ├── R
│       └── Rscript
├── biosoft
│   ├── bamdst
│   ├── bin
│   │   ├── CNCB
│   │   ├── ChIP
│   │   ├── annovar
│   │   ├── denovo_TGS
│   │   ├── denovo_survey
│   │   ├── medical_rna
│   │   ├── R -> /public/software/VersionHub/R/4.4.2/R
│   │   └── Rscript -> /public/software/VersionHub/R/4.4.2/Rscript
│   ├── bioinformatics
│   ├── bsmap-2.90
│   ├── cnvkit
│   ├── container
│   ├── database
│   ├── gatk-4.3.0.0
│   ├── manta-1.6.0
│   ├── miniconda3
│   ├── qc_utils
│   └── workflow
│       ├── pipelines
│       ├── scripts
│       └── single_cell.py
└── skill_test
    ├── 10x-scrna-analysis
    ├── 10x-spatial-scrna-analysis
    ├── 16s-rrna-qiime2-analysis
    ├── atac-seq-analysis
    ├── chip-analysis
    ├── comparative-genomics-analysis
    ├── human-illness-wes-analysis
    ├── human-tumor-wes-analysis
    ├── human-tumor-wgs-analysis
    ├── rna-analysis
    └── single-cell-rna-matrix-analysis
```

## 基础加载方式

VersionHub 生物信息命令的集中入口为：

```bash
export VERSIONHUB_ROOT=/public/software/VersionHub
export BIOSOFT_ROOT=/public/software/VersionHub/biosoft
export PATH="$BIOSOFT_ROOT/bin:$PATH"
```

脚本不应只写裸命令并依赖交互式 shell。对关键步骤，优先使用绝对路径，例如：

```bash
/public/software/VersionHub/biosoft/bin/fastp --help
/public/software/VersionHub/biosoft/bin/samtools --help
/public/software/VersionHub/biosoft/bin/bcftools --help
```

## R 运行时

已确认 `/public/software/VersionHub/R` 下存在下列版本目录：

```text
3.6.3
4.0.0  4.0.1  4.0.2  4.0.3
4.1.0  4.1.1  4.1.2  4.1.3
4.2.0  4.2.1  4.2.2  4.2.3
4.3.0  4.3.1  4.3.2  4.3.3
4.4.0  4.4.1  4.4.2  4.4.3
4.5.1  4.5.2
```

`biosoft/bin` 中的默认入口明确指向 R 4.4.2：

```text
/public/software/VersionHub/biosoft/bin/R
  -> /public/software/VersionHub/R/4.4.2/R

/public/software/VersionHub/biosoft/bin/Rscript
  -> /public/software/VersionHub/R/4.4.2/Rscript
```

因此涉及 R、Bioconductor 或 R 脚本的任务，默认使用：

```bash
/public/software/VersionHub/R/4.4.2/Rscript --vanilla analysis.R
```

当前快照尚未完成各版本可执行状态、各版本 library 包数量及包版本的逐项复核。判断某个 R 包是否受支持时，必须在运行前检查：

```bash
/public/software/VersionHub/R/4.4.2/Rscript --vanilla -e \
  'p <- "PACKAGE_NAME"; quit(status = if (requireNamespace(p, quietly=TRUE)) 0 else 1)'
```

因此，`Seurat`、`DESeq2`、`edgeR`、`SingleR`、`CellChat`、`monocle3` 等具体 R 包在本快照中应暂记为 `unknown`，不能从其他环境的依赖说明直接继承。

## Conda 与 Python

已确认 Miniconda 根目录存在：

```text
/public/software/VersionHub/biosoft/miniconda3
```

`biosoft/bin` 中还存在以下通用入口：

```text
/public/software/VersionHub/biosoft/bin/python
/public/software/VersionHub/biosoft/bin/pip
```

当前快照没有完成 `miniconda3/envs` 的环境名、Python 版本和 `conda-meta` 包版本复核。生成任务脚本时：

1. 不要猜测环境名，也不要直接照搬其他集群的 Conda 环境路径。
2. 若只需执行已有工作流入口，优先使用 VersionHub 自带 workflow 或已确认的绝对命令路径。
3. 若任务明确依赖 Python 包，应先通过目标 Python 的 `import` 测试确认。
4. 不要在共享 VersionHub 目录中安装或升级包；需要补充依赖时使用用户自己的环境。

## 通用命令行软件

下表中的路径均由 11250 远程目录枚举确认。除路径或文件名中明确包含版本号者外，版本暂记为 `unknown`；正式运行前应执行 `--version` 或最小输入测试。

| 软件/入口 | 已确认路径 | 版本线索 | 主要用途 | 判断 |
| --- | --- | --- | --- | --- |
| `fastp` | `/public/software/VersionHub/biosoft/bin/fastp` | unknown | FASTQ 质控、过滤、接头去除 | path-confirmed |
| `FastQC` | `/public/software/VersionHub/biosoft/bin/fastqc` | unknown | 原始测序数据质量报告 | path-confirmed |
| `seqkit` | `/public/software/VersionHub/biosoft/bin/seqkit` | unknown | FASTA/FASTQ 统计、筛选和转换 | path-confirmed |
| `seqtk` | `/public/software/VersionHub/biosoft/bin/seqtk` | unknown | FASTA/FASTQ 抽样和基础处理 | path-confirmed |
| `bwa` | `/public/software/VersionHub/biosoft/bin/bwa` | unknown | DNA 短读段比对 | path-confirmed |
| `bowtie2` | `/public/software/VersionHub/biosoft/bin/bowtie2` | unknown | 短读段比对 | path-confirmed |
| `bowtie2-build` | `/public/software/VersionHub/biosoft/bin/bowtie2-build` | unknown | Bowtie2 索引构建 | path-confirmed |
| `samtools` | `/public/software/VersionHub/biosoft/bin/samtools` | unknown | SAM/BAM/CRAM 处理 | path-confirmed |
| `sambamba` | `/public/software/VersionHub/biosoft/bin/sambamba` | unknown | BAM 排序、索引和过滤 | path-confirmed |
| `bcftools` | `/public/software/VersionHub/biosoft/bin/bcftools` | unknown | VCF/BCF 处理、过滤和统计 | path-confirmed |
| `bgzip` | `/public/software/VersionHub/biosoft/bin/bgzip` | unknown | 基因组文本块压缩 | path-confirmed |
| `tabix` | `/public/software/VersionHub/biosoft/bin/tabix` | unknown | 压缩区间文件索引和查询 | path-confirmed |
| `bedtools` | `/public/software/VersionHub/biosoft/bin/bedtools` | unknown | 基因组区间运算 | path-confirmed |
| `gatk` | `/public/software/VersionHub/biosoft/bin/gatk` | 链接到 `gatk-4.3.0.0/gatk` | Germline/Somatic 变异分析 | path-confirmed |
| GATK local jar | `/public/software/VersionHub/biosoft/bin/gatk-package-4.6.2.0-local.jar` | 4.6.2.0 | GATK Java 入口 | path-confirmed |
| GATK 独立目录 | `/public/software/VersionHub/biosoft/gatk-4.3.0.0` | 4.3.0.0 | GATK 独立安装 | path-confirmed |
| `vardict-java` | `/public/software/VersionHub/biosoft/bin/vardict-java` | unknown | SNV/Indel，尤其肿瘤变异检测 | path-confirmed |
| `VarDict` | `/public/software/VersionHub/biosoft/bin/VarDict` | 链接到 `vardict-java` | VarDict 兼容入口 | path-confirmed |
| `delly` | `/public/software/VersionHub/biosoft/bin/delly` | unknown | 结构变异检测 | path-confirmed |
| Manta 配置入口 | `/public/software/VersionHub/biosoft/bin/configManta.py` | 链接到 Manta 1.6.0 | 结构变异流程配置 | path-confirmed |
| Manta 安装目录 | `/public/software/VersionHub/biosoft/manta-1.6.0` | 1.6.0 | 结构变异检测 | path-confirmed |
| CNVkit Python 入口 | `/public/software/VersionHub/biosoft/bin/cnvkit.py` | 版本待复核 | CNV 检测与分段 | path-confirmed |
| `mosdepth` | `/public/software/VersionHub/biosoft/bin/mosdepth` | unknown | BAM 覆盖度统计 | path-confirmed |
| `pandepth` | `/public/software/VersionHub/biosoft/bin/pandepth` | unknown | 测序深度统计 | path-confirmed |
| `bamdst` | `/public/software/VersionHub/biosoft/bin/bamdst` | 链接到 `biosoft/bamdst/bamdst` | 靶区覆盖度与 QC | path-confirmed |
| `msisensor2` | `/public/software/VersionHub/biosoft/bin/msisensor2` | unknown | MSI 检测 | path-confirmed |
| fgbio jar | `/public/software/VersionHub/biosoft/bin/fgbio-3.0.0.jar` | 3.0.0 | UMI 与 BAM 处理 | path-confirmed |
| Picard jar | `/public/software/VersionHub/biosoft/bin/picard.jar` | unknown | BAM 指标、排序、重复标记 | path-confirmed |
| `bsmap` | `/public/software/VersionHub/biosoft/bin/bsmap` | 链接到 BSMAP 2.90 | Bisulfite reads 比对 | path-confirmed |
| `methratio.py` | `/public/software/VersionHub/biosoft/bin/methratio.py` | unknown | 甲基化比例计算 | path-confirmed |
| `methdiff.py` | `/public/software/VersionHub/biosoft/bin/methdiff.py` | unknown | 差异甲基化分析 | path-confirmed |
| `pgcgap` | `/public/software/VersionHub/biosoft/bin/pgcgap` | unknown | 原核比较基因组流程 | path-confirmed |
| `vcf2phylip.py` | `/public/software/VersionHub/biosoft/bin/vcf2phylip.py` | unknown | VCF 转系统发育矩阵 | path-confirmed |
| DRMAA 命令 | `/public/software/VersionHub/biosoft/bin/drmaa-run` | unknown | 集群任务接口 | path-confirmed |

## 工作流入口

VersionHub 提供统一工作流目录：

```text
/public/software/VersionHub/biosoft/workflow
├── main.py
├── single_cell.py
├── utils.py
├── scripts
│   ├── cluster.R
│   ├── pseudotime.R
│   ├── qc.R
│   └── single_cell.slurm
└── pipelines
```

已确认 `pipelines` 下存在以下流程目录：

| 类别 | 流程目录 |
| --- | --- |
| 单细胞与空间组学 | `10x_scrna`, `10x_spatial_scrna`, `single_cell_rna` |
| RNA 与表达分析 | `rna`, `medical_rna`, `rna_differential_expression` |
| 人类 WES/WGS | `human_illness_wes`, `human_tumor_wes`, `human_tumor_wgs`, `wgs_human_ill`, `call_variants` |
| 表观组与染色质 | `atac-seq`, `chip`, `cuttag`, `dnase-seq`, `mnase-seq`, `meth` |
| RNA 修饰与互作 | `bid-seq`, `chirp-seq`, `chrrna-seq`, `circrna-seq`, `clip-seq`, `gro-seq`, `merip-seq`, `miclip-seq`, `pro-seq`, `ribo-seq`, `ric-seq` |
| 三维基因组 | `hic-seq` |
| 微生物与比较基因组 | `comparative_genomics`, `qiime2` |
| 组装与调查 | `denovo_survey`, `denovo_tgs` |
| 临床与肿瘤专项 | `cnvanno`, `ctdna_umi`, `hla_typing`, `pancancer` |

另有一个生物信息工作流包：

```text
/public/software/VersionHub/biosoft/bioinformatics/bioagent_workflow
```

这些目录证明流程资源存在，但本次未逐一确认每个 `main.py` 的参数、输入 schema、依赖激活方式和最小运行结果。仅凭目录名判断具体论文流程时，应标为 `partial`，并在执行前读取对应流程的帮助或配置文件。

## 容器镜像

11250 中存在大量 `.sif` 生物信息镜像。镜像资产已确认，但本次尚未确认宿主机可调用的 Apptainer/Singularity 入口，因此容器类任务总体判断为 `partial`，直到容器运行时通过检查。

### 综合流程镜像

| 镜像 | 路径 | 用途判断 |
| --- | --- | --- |
| 人类遗传病 WGS/WES | `/public/software/VersionHub/biosoft/bin/WGE_human_ill.sif` | 人类遗传病全基因组/外显子流程 |
| 人类遗传病 WES | `/public/software/VersionHub/biosoft/bin/human_illness_WES.sif` | WES 流程 |
| 人类肿瘤 WES | `/public/software/VersionHub/biosoft/bin/human_tumor_WES.sif` | 肿瘤 WES 流程 |
| 人类肿瘤 WGS | `/public/software/VersionHub/biosoft/bin/human_tumor_WGS.sif` | 肿瘤 WGS 流程 |
| RNA alignment | `/public/software/VersionHub/biosoft/bin/rna_alignment.sif` | RNA 比对流程 |
| QIIME2 | `/public/software/VersionHub/biosoft/bin/qiime2.sif` | 16S/微生物组流程 |
| Mosdepth | `/public/software/VersionHub/biosoft/bin/mosdepth.sif` | 覆盖度统计 |
| 报告 | `/public/software/VersionHub/biosoft/bin/md_report.sif` | 报告生成 |

### CNCB 专项镜像

`/public/software/VersionHub/biosoft/bin/CNCB` 下已确认以下镜像：

```text
ATAC-seq/atacseq.sif
BID-seq/BID-seq.sif
BS-seq/BSseq.sif
CLIP-seq/CLIP.sif
ChIRP-seq/ChIRPseq.sif
DNase-seq/dnaseseq.sif
End-seq/EndSeq.sif
GLORI-seq/newGLORI.sif
GRO-seq/groseq.sif
HiC/Hi-C.sif
MNase-seq/mnaseseq.sif
MeDIP-seq/MeDIP-seq.sif
MeRIP-seq/MeRIPseq.sif
PARIS/paris.sif
RIC-seq/RIC-seq.sif
Ribo-seq/riboseq.sif
SHAPE-MaP/shapemap.sif
SPRITE/SPRITE.sif
WGBS/wgbs.sif
chrRNA-seq/chrrnaseq.sif
circRNA-seq/circRNA.sif
lncRNA-seq/lncRNAseq.sif
m1A-map-seq/m1A-map.sif
m1A-quant-seq/m1A-quant.sif
m7G-map-seq/m7G.sif
mNET-seq/mnetseq.sif
miCLIP-seq/newmiCLIPseq.sif
miRNA-seq/miRNA.sif
pro-seq/proseq.sif
scTCR_scBCR/airrflow.sif
smRNA-seq/smallRNAseq.sif
```

### ChIP、组装和单细胞专项镜像

| 类别 | 已确认路径或镜像 |
| --- | --- |
| ChIP-seq | `/public/software/VersionHub/biosoft/bin/ChIP/sif/chip_alignment.sif`, `chip_deeptools.sif`, `chip_fastp.sif`, `chip_homer.sif`, `chip_macs2.sif` |
| De novo TGS | `/public/software/VersionHub/biosoft/bin/denovo_TGS/sif/assembly.sif`, `annotation_function.sif`, `annotation_polish.sif`, `busco.sif`, `helixer_v0.3.6.sif`, `hite.3.3.3.sif` |
| De novo survey | `/public/software/VersionHub/biosoft/bin/denovo_survey/sif/denovo_survey.sif`, `filter.sif` |
| 10x 单细胞 | `/public/software/VersionHub/biosoft/bin/liut/sif/cellranger_7.1.0.sif`, `seurat5_sccustomize.sif`, `singler_doubletfinder.sif` |
| 10x 空间转录组 | `/public/software/VersionHub/biosoft/bin/liut/sif/spaceranger.sif` |
| HLA typing | `/public/software/VersionHub/biosoft/bin/liut/sif/hla_typing.sif` |
| SV 注释 | `/public/software/VersionHub/biosoft/bin/liut/sif/AnnotSV_3.5.3.sif`, `knotAnnotSV.sif` |

`/public/software/VersionHub/biosoft/container` 下还存在同类镜像的另一套组织结构。生成脚本时优先使用上表中已经给出完整路径的 `biosoft/bin` 镜像；若改用 `biosoft/container`，必须先验证目标镜像的确切路径和更新时间。

## 参考数据库与索引

数据库根目录：

```text
/public/software/VersionHub/biosoft/database
```

### 通用基因组与变异数据库

| 资源 | 已确认路径 | 用途 | 判断 |
| --- | --- | --- | --- |
| hg38 | `/public/software/VersionHub/biosoft/database/hg38` | 人类 hg38 参考资源 | directory-confirmed |
| hg38 HISAT2 索引 | `/public/software/VersionHub/biosoft/database/hg38/ht2` | RNA-seq 比对索引 | directory-confirmed |
| 通用 hg19 | `/public/software/VersionHub/biosoft/database/db/hg19` | hg19 参考资源 | directory-confirmed |
| 通用 hg38 | `/public/software/VersionHub/biosoft/database/db/hg38` | hg38 参考资源 | directory-confirmed |
| GATK 数据 | `/public/software/VersionHub/biosoft/database/db/GATK` | GATK 参考/资源文件 | directory-confirmed |
| ClinVar | `/public/software/VersionHub/biosoft/database/db/clinvar` | 临床变异注释 | directory-confirmed |
| ANNOVAR humandb | `/public/software/VersionHub/biosoft/database/annovar/humandb` | ANNOVAR 注释库 | directory-confirmed |
| CNVkit data | `/public/software/VersionHub/biosoft/database/cnvkit/data` | CNVkit 参考资源 | directory-confirmed |
| AnnotSV 3.5.3 注释 | `/public/software/VersionHub/biosoft/database/cnvanno/AnnotSV_3.5.3_anno` | 结构变异注释 | directory-confirmed |
| HLA 索引 | `/public/software/VersionHub/biosoft/database/hla_typing/hlaidx` | HLA typing | directory-confirmed |
| KIR 索引 | `/public/software/VersionHub/biosoft/database/hla_typing/kiridx` | KIR typing | directory-confirmed |

### 单细胞与空间组学资源

```text
/public/software/VersionHub/biosoft/database/10x_scrna/genome
/public/software/VersionHub/biosoft/database/10x_spatial_scRNA
/public/software/VersionHub/biosoft/database/10x_spatial_scrna
/public/software/VersionHub/biosoft/database/celldex
/public/software/VersionHub/biosoft/database/module/cellranger
/public/software/VersionHub/biosoft/database/module/findallmarker
/public/software/VersionHub/biosoft/database/module/merge_harmony
/public/software/VersionHub/biosoft/database/module/annotation
/public/software/VersionHub/biosoft/database/module/report
/public/software/VersionHub/biosoft/database/scTCR_scBCR/Reference
```

大小写不同的 `10x_spatial_scRNA` 与 `10x_spatial_scrna` 目录同时存在。Linux 路径区分大小写，脚本不得互换这两个路径。

### 表观组、RNA 修饰与结构资源

已确认下列任务专用数据库或 References 目录：

```text
ATAC-seq/motifs
BID-seq/References
BS-seq/GRCm39
BS-seq/hg38
CLIP-seq/References
ChIP/genome
ChIRP-seq/hg38
ChIRP-seq/hg38_repeats
DNase-seq/hg38
GLORI-seq/References
MeRIP-seq/hg38_chr_star_index
PARIS/reference_data
RIC-seq
Ribo-seq/References
SHAPE-MaP/References
WGBS/References
chrRNA-seq
circRNA-seq
lncRNA-seq/References
lncRNA-seq/r_database
m1A-map-seq/Reference
m1A-quant-seq/Reference
m7G-map-seq/Reference
mNET-seq/References
miCLIP-seq/hg38_bowtie_index
miRNA-seq/reference
smRNA-seq/References
```

以上路径均相对于 `/public/software/VersionHub/biosoft/database`。

### 其他专项资源

```text
/public/software/VersionHub/biosoft/database/denovo_tgs/database
/public/software/VersionHub/biosoft/database/human_illness_wes
/public/software/VersionHub/biosoft/database/wgs_human_ill
/public/software/VersionHub/biosoft/database/medical_rna/genome
/public/software/VersionHub/biosoft/database/qiime2
/public/software/VersionHub/biosoft/database/skill_resources/10x_spatial_scrna
/public/software/VersionHub/biosoft/database/skill_resources/HiC-seq
```

## 典型调用片段

### FASTQ 质控

```bash
set -euo pipefail
BIOBIN=/public/software/VersionHub/biosoft/bin
"$BIOBIN/fastp" \
  -i sample_R1.fastq.gz -I sample_R2.fastq.gz \
  -o clean_R1.fastq.gz -O clean_R2.fastq.gz \
  --html sample.fastp.html --json sample.fastp.json
```

### DNA 比对和 BAM 处理

```bash
set -euo pipefail
BIOBIN=/public/software/VersionHub/biosoft/bin
test -f reference.fa || { echo "missing reference.fa" >&2; exit 1; }
"$BIOBIN/bwa" mem -t "${SLURM_CPUS_PER_TASK:-4}" reference.fa R1.fq.gz R2.fq.gz \
  | "$BIOBIN/samtools" sort -@ "${SLURM_CPUS_PER_TASK:-4}" -o sample.sorted.bam -
"$BIOBIN/samtools" index sample.sorted.bam
```

### VCF 压缩和索引

```bash
BIOBIN=/public/software/VersionHub/biosoft/bin
"$BIOBIN/bgzip" -c variants.vcf > variants.vcf.gz
"$BIOBIN/tabix" -p vcf variants.vcf.gz
"$BIOBIN/bcftools" stats variants.vcf.gz > variants.stats.txt
```

### R 脚本

```bash
RSCRIPT=/public/software/VersionHub/R/4.4.2/Rscript
test -x "$RSCRIPT" || { echo "Rscript is unavailable" >&2; exit 1; }
"$RSCRIPT" --vanilla analysis.R
```

### SIF 镜像运行前检查

```bash
IMAGE=/public/software/VersionHub/biosoft/bin/qiime2.sif
test -r "$IMAGE" || { echo "missing image: $IMAGE" >&2; exit 1; }
if command -v apptainer >/dev/null 2>&1; then
  apptainer exec "$IMAGE" qiime --help
elif command -v singularity >/dev/null 2>&1; then
  singularity exec "$IMAGE" qiime --help
else
  echo "SIF image exists, but no verified container runtime is available" >&2
  exit 1
fi
```

不要在容器入口未确认时假定镜像内一定包含与镜像名相同的命令。

## 任务到依赖的匹配

| 任务类型 | 当前判断 | 推荐依赖 | 关键限制 |
| --- | --- | --- | --- |
| FASTQ 质控、过滤、接头去除 | supported | `fastp`, `fastqc`, `seqkit`, `seqtk` | 路径已确认，版本待复核 |
| DNA 短读段比对 | supported | `bwa`, `bowtie2`, `samtools` | 参考 FASTA/索引的物种和版本需确认 |
| BAM 排序、索引、过滤 | supported | `samtools`, `sambamba`, Picard jar | Java 版本与 Picard 版本待复核 |
| VCF/BCF 处理 | supported | `bcftools`, `bgzip`, `tabix` | 命令版本待复核 |
| Germline/Somatic SNV/Indel | partial | GATK 4.3.0.0 或 4.6.2.0 jar、VarDict | 需确认 Java、参考资源和具体调用入口 |
| 结构变异 | partial | Manta 1.6.0、`delly` | 需做目标样本和 Python 兼容性测试 |
| CNV | partial | `cnvkit.py`, CNVkit data | CNVkit 包版本与 Python 环境待复核 |
| 覆盖度和深度 | supported | `mosdepth`, `pandepth`, `bamdst` | 版本待复核 |
| MSI | partial | `msisensor2` | 模型/参考资源需确认 |
| UMI | partial | fgbio 3.0.0 jar、`ctdna_umi` pipeline | Java 与流程参数待复核 |
| RNA-seq 比对 | partial | `rna_alignment.sif`, `rna`/`medical_rna` pipeline | 容器运行时及 STAR/HISAT2 入口未复核 |
| RNA-seq 差异表达 | partial | `rna_differential_expression` pipeline、R 4.4.2 | DESeq2/edgeR/limma 包未完成复核 |
| 10x 单细胞 RNA-seq | partial | Cell Ranger 7.1.0 镜像、`10x_scrna` pipeline | 容器运行时、参考 genome 和下游 R 包需复核 |
| 空间转录组 | partial | Space Ranger 镜像、`10x_spatial_scrna` pipeline | 镜像版本及参考资源需复核 |
| 单细胞矩阵下游分析 | partial | `seurat5_sccustomize.sif`, `singler_doubletfinder.sif`, `single_cell.py` | 镜像运行时与 R 包版本需复核 |
| ChIP-seq | partial | ChIP SIF 组件、`chip` pipeline、`ChIP/genome` | 多镜像之间的输入输出约定需确认 |
| ATAC-seq | partial | `atacseq.sif`, `atac-seq` pipeline、motifs 目录 | 容器运行时与参考版本需确认 |
| DNA 甲基化/WGBS | partial | BSMAP 2.90、`wgbs.sif`、BS-seq/WGBS references | 参考版本和容器入口需确认 |
| RNA 修饰与 RNA 互作 | partial | CNCB 专项 SIF 与对应 References | 容器入口和样本协议需确认 |
| Hi-C/SPRITE | partial | `Hi-C.sif`, `SPRITE.sif`, skill resources | 参考资源和容器运行时需确认 |
| 原核比较基因组 | partial | `pgcgap`, `comparative_genomics` pipeline | pgcgap 的具体版本和附属工具未复核 |
| 16S/QIIME2 | partial | `qiime2.sif`, `qiime2` pipeline/database | QIIME2 版本、插件和运行时未复核 |
| De novo TGS | partial | assembly/BUSCO/Helixer/HiTE 镜像、`denovo_tgs` pipeline | 镜像间流程契约和数据库版本需确认 |
| HLA/KIR typing | partial | `hla_typing.sif`, HLA/KIR 索引 | 索引版本和适用参考基因组需确认 |
| 工作流调度 | partial | `biosoft/workflow`, DRMAA 命令 | Python 环境和调度器参数待复核 |

## 已知缺口与风险

1. R 4.4.2 是 `biosoft/bin/Rscript` 的明确链接目标，但具体 R/Bioconductor 包和版本尚未完成当前集群复核。
2. 多个 R 版本目录存在，不代表所有版本都完整可执行或带有相同包库；不能随意切换版本。
3. Miniconda 根目录存在，但本快照未确认环境名、Python 版本和 `conda-meta` 包清单。
4. `.sif` 镜像大量存在，但 Apptainer/Singularity 宿主入口尚未确认；镜像任务默认判为 `partial`。
5. 数据库目录只确认存在，未校验物种、assembly 版本、索引格式、文件大小、校验和及权限。
6. `gatk` 默认符号链接指向 4.3.0.0，同时 `biosoft/bin` 中另有 4.6.2.0 local jar；脚本必须明确选择版本，不能混用。
7. `cnvkit.py`、Manta、部分流程入口依赖特定 Python 版本；调用前必须做 `--help` 或最小样例测试。
8. 工作流目录存在并不保证其所有内部依赖仍可用。执行前应读取对应 pipeline 配置并验证绝对路径。
9. Linux 路径区分大小写；数据库中存在大小写相近目录，脚本必须复制实际路径。
10. 不要修改 `/public/software/VersionHub` 共享环境，也不要在其中执行 `pip install`、`conda install` 或写入数据库目录。

## 环境判断建议

1. 先按任务类型从“任务到依赖的匹配”中选候选工具，再检查表中给出的绝对路径。
2. 命令行任务至少执行一次 `--version`/`--help` 和最小输入测试后，再从 `path-confirmed` 提升为实际可运行的 `supported`。
3. R 任务必须报告并优先使用 `/public/software/VersionHub/R/4.4.2/Rscript`，同时逐个检查所需包。
4. 容器任务必须同时确认镜像文件和 Apptainer/Singularity 运行时；只存在 `.sif` 时判断为 `partial`。
5. 数据库依赖必须精确到物种、assembly、release 和索引类型；只有上级目录时判断为 `partial`。
6. 遇到 GATK 时明确区分默认 4.3.0.0 入口与 4.6.2.0 jar，并校验 Java 兼容性。
7. 未记录的依赖统一标记为 `unknown`；不要用其他集群的依赖说明补全。
