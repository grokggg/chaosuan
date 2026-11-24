# VersionHub 生物信息依赖库参考

本文档记录 `/public/software/VersionHub` 的依赖结构、可用环境、命令行软件、R 包能力和任务匹配建议，用于 `literature_workflow` 在拆解论文计算任务后判断当前环境是否支持对应依赖。

## 依赖库总体结构

```text
/public/software/VersionHub
├── R
│   └── 4.4.2
│       ├── R
│       ├── Rscript
│       ├── depends
│       │   ├── include
│       │   ├── lib
│       │   └── share
│       └── library
│           ├── AnnotationDbi
│           ├── AnnotationHub
│           ├── BPCells
│           ├── Biobase
│           ├── Biostrings
│           ├── CellChat
│           ├── ChIPseeker
│           ├── ComplexHeatmap
│           ├── DESeq2
│           ├── DNAcopy
│           ├── DOSE
│           ├── EnhancedVolcano
│           ├── GenomicAlignments
│           ├── GenomicFeatures
│           ├── GenomicRanges
│           ├── HDF5Array
│           ├── KEGGREST
│           ├── PCAtools
│           ├── Rsamtools
│           ├── Seurat
│           ├── SeuratObject
│           ├── SeuratWrappers
│           ├── SingleCellExperiment
│           ├── SingleR
│           ├── SummarizedExperiment
│           ├── clusterProfiler
│           ├── edgeR
│           ├── fgsea
│           ├── limma
│           ├── maftools
│           ├── methylKit
│           ├── monocle3
│           └── tidyverse
├── biosoft
│   ├── BSMAPz
│   │   ├── bsmapz
│   │   ├── bsp2sam.py
│   │   ├── methdiff.py
│   │   ├── methratio.py
│   │   └── sam2bam.sh
│   ├── VarDict-1.8.3
│   ├── apptainer
│   ├── bamdst
│   ├── bin
│   │   ├── FastTree
│   │   ├── FastTreeMP
│   │   ├── abricate
│   │   ├── aragorn
│   │   ├── bamdst
│   │   ├── barrnap
│   │   ├── bcftools
│   │   ├── bedtools
│   │   ├── bgzip
│   │   ├── bowtie2
│   │   ├── bowtie2-build
│   │   ├── bwa
│   │   ├── fastp
│   │   ├── fgbio
│   │   ├── gatk
│   │   ├── manta
│   │   ├── mosdepth
│   │   ├── msisensor2
│   │   ├── pandepth
│   │   ├── pgcgap
│   │   ├── picard
│   │   ├── sambamba
│   │   ├── samtools
│   │   ├── seqkit
│   │   ├── seqtk
│   │   ├── tabix
│   │   └── vardict
│   ├── cnvkit
│   ├── database
│   │   ├── 10x_scrna
│   │   ├── 10x_spatial_scrna
│   │   ├── ATAC-seq
│   │   ├── CLIP-seq
│   │   ├── ChIP
│   │   ├── ChIRP-seq
│   │   ├── DNase-seq
│   │   ├── End-seq
│   │   ├── MNase-seq
│   │   ├── MeRIP-seq
│   │   ├── PARIS
│   │   ├── RIC-seq
│   │   ├── Ribo-seq
│   │   ├── annovar
│   │   ├── celldex
│   │   ├── chrRNA-seq
│   │   ├── circRNA-seq
│   │   ├── cnvanno
│   │   ├── cnvkit
│   │   ├── db
│   │   ├── denovo_tgs
│   │   ├── hg38
│   │   ├── hla_typing
│   │   ├── human_illness_wes
│   │   ├── medical_rna
│   │   ├── miCLIP-seq
│   │   ├── miRNA-seq
│   │   ├── module
│   │   ├── qiime2
│   │   └── wgs_human_ill
│   ├── gatk-4.3.0.0
│   │   ├── gatk
│   │   ├── gatk-package-4.3.0.0-local.jar
│   │   ├── gatk-package-4.3.0.0-spark.jar
│   │   └── gatkPythonPackageArchive.zip
│   ├── manta-1.6.0
│   ├── miniconda3
│   │   └── envs
│   │       ├── apptainer
│   │       ├── bcftools
│   │       ├── bedtools
│   │       ├── bowtie2
│   │       ├── bsmap
│   │       ├── bwa
│   │       ├── cnvkit
│   │       ├── cnvkit-1
│   │       ├── cnvkit-2
│   │       ├── drmaa
│   │       ├── fastp
│   │       ├── fgbio
│   │       ├── fuse-overlayfs
│   │       ├── manta
│   │       ├── msisensor2
│   │       ├── ncurses
│   │       ├── parallel
│   │       ├── pgcgap
│   │       ├── pgcgap-1
│   │       ├── picard
│   │       ├── python
│   │       ├── sambamba
│   │       ├── samtools
│   │       ├── seqkit
│   │       ├── seqtk
│   │       ├── snakemake
│   │       └── vardict-java
│   ├── pgcgap
│   └── qc_utils
│       ├── extractUmisFromBam.py
│       ├── merge_all_qc.py
│       ├── merge_qc.py
│       ├── methdiff.py
│       ├── methratio.py
│       ├── svfilter.py
│       ├── umi_qc.py
│       └── vcf_filter.py
└── scripts
    ├── CellChat
    ├── Miniconda3-latest-Linux-x86_64.sh
    ├── base_depends.yaml
    ├── check
    ├── compile.x11.sh
    ├── install_r_package.py
    ├── log
    ├── monocle3
    ├── seurat-wrappers
    └── test
```

## Python 与 Conda 环境清单

| 环境路径 | 关键依赖 | 可执行任务 |
|---|---|---|
| `/public/software/VersionHub/biosoft/miniconda3/envs/python` | `python=3.10.0` | 通用 Python 脚本运行，适合作为轻量脚本执行环境。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/snakemake` | `python=3.13.9`, `snakemake=9.13.7`, `numpy=2.3.4`, `pandas=2.3.3` | Snakemake 工作流编排，适合论文复现实验中多步骤 pipeline 调度。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/pgcgap` | `python=3.7.12`, `pgcgap=1.0.34`, `abricate=1.0.1`, `abyss=2.3.4`, `aragorn=1.2.41`, `barrnap=0.9`, `bedtools=2.27.1`, `blast=2.16.0`, `canu=1.4`, `cd-hit=4.8.1`, `diamond=2.1.10`, `fastp=0.23.2`, `fasttree=2.2.0`, `hmmer=3.4`, `mafft=7.526`, `mash=2.3`, `mmseqs2=13.45111`, `muscle=5.3`, `r-base=4.3.1`, `seaborn=0.12.2` | 原核基因组注释、泛基因组、比较基因组、耐药基因筛查、毒力基因筛查、系统发育分析。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/pgcgap-1` | `python=3.9.15`, `pgcgap=1.0.35`, `abricate=1.0.1`, `abyss=2.3.5`, `bcftools=1.16`, `bedtools=2.31.1`, `blast=2.16.0`, `bowtie2=2.5.4`, `bwa=0.7.18`, `canu=2.1.1`, `diamond=2.1.10`, `fastp=0.23.2`, `fasttree=2.2.0`, `freebayes=1.3.6`, `hmmer=3.4`, `mafft=7.526`, `minimap2=2.28`, `mmseqs2=16.747c6`, `samtools=1.16.1`, `seqtk=1.4`, `spades=3.15.5` | 更完整的原核组装、比对、变异检测、注释、比较基因组和系统发育流程。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/cnvkit` | `python=3.10.19`, `cnvkit=0.9.12`, `biopython=1.85`, `numpy=1.26.4`, `pandas=2.3.3`, `pysam=0.23.3`, `scipy=1.15.2`, `r-base=4.4.3` | CNV 检测、拷贝数分段、测序覆盖度建模、肿瘤样本 CNV 分析。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/cnvkit-2` | `python=3.10.19`, `cnvkit=0.9.12`, `biopython=1.85`, `numpy=1.26.4`, `pandas=2.3.3`, `pysam=0.23.3`, `scipy=1.15.2`, `r-base=4.4.3` | CNV 检测、拷贝数分段、测序覆盖度建模、肿瘤样本 CNV 分析。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/cnvkit-1` | 未检测到 `conda-meta` 包元数据 | 目录存在但缺少可确认包元数据，依赖判断时不要优先使用。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/manta` | `python=2.7.18`, `manta=1.6.0` | WGS/WES 结构变异检测。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/bsmap` | `python=2.7.18`, `bsmap=2.90`, `samtools=1.21` | Bisulfite sequencing 比对、DNA 甲基化分析。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/drmaa` | `python=3.13.5`, `drmaa=0.7.9` | 集群任务调度接口，适合需要 DRMAA 的 workflow。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/vardict-java` | `python=3.13.5`, `r-base=4.3.1`, `vardict-java=1.8.3` | SNV 和 Indel 变异检测，适合肿瘤突变分析。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/fgbio` | `python=3.14.0`, `fgbio=3.0.0`, `r-base=4.5.1` | UMI 处理、BAM 处理、测序数据 QC。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/bowtie2` | `python=3.8.20`, `bowtie2=2.4.1` | 短 reads 比对和索引构建。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/bwa` | `bwa=0.7.19` | WGS、WES、RNA-seq reads 到参考基因组比对。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/samtools` | `samtools=1.13` | BAM、SAM、CRAM 文件处理。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/bcftools` | `bcftools=1.11` | VCF、BCF 文件处理、过滤、统计。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/bedtools` | `bedtools=2.31.1` | BED、GFF、VCF 等基因组区间操作。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/fastp` | `fastp=0.23.2` | FASTQ 质控、接头去除、reads 过滤。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/seqkit` | `seqkit=2.10.0` | FASTA、FASTQ 文件统计、筛选、格式转换。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/seqtk` | `seqtk=1.5` | FASTA、FASTQ 文件抽样、转换、基础处理。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/sambamba` | `sambamba=1.0.1` | BAM 排序、索引、过滤、markdup。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/msisensor2` | `msisensor2=0.1` | 微卫星不稳定性 MSI 检测。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/apptainer` | `apptainer=1.4.2` | 运行 `.sif` 容器镜像。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/fuse-overlayfs` | `fuse-overlayfs=1.15` | 容器 overlay 文件系统支持。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/parallel` | `parallel=20260422` | GNU parallel 并行任务执行。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/ncurses` | `ncurses=6.4.20240210` | 终端库依赖，通常作为底层运行依赖。 |
| `/public/software/VersionHub/biosoft/miniconda3/envs/picard` | 未检测到 `conda-meta` 包元数据 | 目录存在但缺少可确认包元数据，优先使用 `/public/software/VersionHub/biosoft/bin/picard` 或 `picard.jar`。 |

## 命令行软件清单

| 命令或文件 | 路径 | 可执行任务 |
|---|---|---|
| `fastp` | `/public/software/VersionHub/biosoft/bin/fastp` | FASTQ 质控、过滤、接头去除、质量报告。 |
| `seqkit` | `/public/software/VersionHub/biosoft/bin/seqkit` | FASTA、FASTQ 统计、提取、去重、格式转换。 |
| `seqtk` | `/public/software/VersionHub/biosoft/bin/seqtk` | FASTA、FASTQ 抽样、子序列提取、格式转换。 |
| `bwa` | `/public/software/VersionHub/biosoft/bin/bwa` | DNA reads 到参考基因组比对。 |
| `bowtie2` | `/public/software/VersionHub/biosoft/bin/bowtie2` | 短 reads 到参考基因组或转录组索引比对。 |
| `bowtie2-build` | `/public/software/VersionHub/biosoft/bin/bowtie2-build` | Bowtie2 索引构建。 |
| `samtools` | `/public/software/VersionHub/biosoft/bin/samtools` | BAM、SAM、CRAM 排序、索引、过滤、统计、格式转换。 |
| `sambamba` | `/public/software/VersionHub/biosoft/bin/sambamba` | BAM 排序、索引、过滤、重复标记，适合高性能 BAM 处理。 |
| `bcftools` | `/public/software/VersionHub/biosoft/bin/bcftools` | VCF、BCF 合并、过滤、统计、注释、变异处理。 |
| `bgzip` | `/public/software/VersionHub/biosoft/bin/bgzip` | VCF、BED、GFF 等文本文件块压缩。 |
| `tabix` | `/public/software/VersionHub/biosoft/bin/tabix` | 压缩基因组区间文件索引与区域查询。 |
| `bedtools` | `/public/software/VersionHub/biosoft/bin/bedtools` | BED、GFF、VCF 区间交集、覆盖度、窗口、注释交叉。 |
| `gatk` | `/public/software/VersionHub/biosoft/bin/gatk` | Germline 和 somatic 变异检测、HaplotypeCaller、BQSR、Mutect2、VCF 处理。 |
| `gatk-package-4.6.2.0-local.jar` | `/public/software/VersionHub/biosoft/bin/gatk-package-4.6.2.0-local.jar` | GATK 4.6.2.0 本地 jar 包。 |
| `gatk` | `/public/software/VersionHub/biosoft/gatk-4.3.0.0/gatk` | GATK 4.3.0.0 独立入口。 |
| `gatk-package-4.3.0.0-local.jar` | `/public/software/VersionHub/biosoft/gatk-4.3.0.0/gatk-package-4.3.0.0-local.jar` | GATK 4.3.0.0 本地 jar 包。 |
| `picard` | `/public/software/VersionHub/biosoft/bin/picard` | BAM 处理、重复标记、测序指标统计。 |
| `picard.jar` | `/public/software/VersionHub/biosoft/bin/picard.jar` | Picard jar 包。 |
| `fgbio` | `/public/software/VersionHub/biosoft/bin/fgbio` | UMI 处理、BAM 处理、测序数据 QC。 |
| `fgbio-3.0.0.jar` | `/public/software/VersionHub/biosoft/bin/fgbio-3.0.0.jar` | fgbio 3.0.0 jar 包。 |
| `manta` | `/public/software/VersionHub/biosoft/bin/manta` | WGS/WES 结构变异检测。 |
| `cnvkit` | `/public/software/VersionHub/biosoft/cnvkit` | CNV 分析相关目录。 |
| `vardict` | `/public/software/VersionHub/biosoft/bin/vardict` | SNV、Indel 变异检测。 |
| `vardict-java` | `/public/software/VersionHub/biosoft/bin/vardict-java` | VarDict Java 入口，适合肿瘤突变检测。 |
| `mosdepth` | `/public/software/VersionHub/biosoft/bin/mosdepth` | BAM 覆盖度和测序深度统计。 |
| `pandepth` | `/public/software/VersionHub/biosoft/bin/pandepth` | 测序深度统计。 |
| `bamdst` | `/public/software/VersionHub/biosoft/bin/bamdst` | 靶区覆盖度和测序深度 QC。 |
| `msisensor2` | `/public/software/VersionHub/biosoft/bin/msisensor2` | MSI 微卫星不稳定性检测。 |
| `FastTree` | `/public/software/VersionHub/biosoft/bin/FastTree` | 快速构建系统发育树。 |
| `FastTreeMP` | `/public/software/VersionHub/biosoft/bin/FastTreeMP` | 多线程快速系统发育树构建。 |
| `abricate` | `/public/software/VersionHub/biosoft/bin/abricate` | 细菌基因组耐药、毒力、质粒等数据库筛查。 |
| `barrnap` | `/public/software/VersionHub/biosoft/bin/barrnap` | rRNA 预测。 |
| `aragorn` | `/public/software/VersionHub/biosoft/bin/aragorn` | tRNA 和 tmRNA 预测。 |
| `pgcgap` | `/public/software/VersionHub/biosoft/bin/pgcgap` | 原核比较基因组综合流程。 |
| `bsmapz` | `/public/software/VersionHub/biosoft/BSMAPz/bsmapz` | Bisulfite reads 比对。 |
| `methratio.py` | `/public/software/VersionHub/biosoft/BSMAPz/methratio.py` | 甲基化比例计算。 |
| `methdiff.py` | `/public/software/VersionHub/biosoft/BSMAPz/methdiff.py` | 差异甲基化分析。 |
| `extractUmisFromBam.py` | `/public/software/VersionHub/biosoft/qc_utils/extractUmisFromBam.py` | 从 BAM 提取 UMI。 |
| `umi_qc.py` | `/public/software/VersionHub/biosoft/qc_utils/umi_qc.py` | UMI 质控。 |
| `vcf_filter.py` | `/public/software/VersionHub/biosoft/qc_utils/vcf_filter.py` | VCF 过滤。 |
| `svfilter.py` | `/public/software/VersionHub/biosoft/qc_utils/svfilter.py` | 结构变异过滤。 |
| `merge_qc.py` | `/public/software/VersionHub/biosoft/qc_utils/merge_qc.py` | QC 结果合并。 |
| `merge_all_qc.py` | `/public/software/VersionHub/biosoft/qc_utils/merge_all_qc.py` | 多样本 QC 结果合并。 |

## 容器镜像清单

| 镜像 | 路径 | 可执行任务判断 |
|---|---|---|
| `WGE_human_ill.sif` | `/public/software/VersionHub/biosoft/bin/WGE_human_ill.sif` | 人类遗传病相关全基因组或外显子流程镜像，具体入口需结合镜像内命令确认。 |
| `human_illness_WES.sif` | `/public/software/VersionHub/biosoft/bin/human_illness_WES.sif` | 人类遗传病 WES 分析流程镜像。 |
| `human_tumor_WES.sif` | `/public/software/VersionHub/biosoft/bin/human_tumor_WES.sif` | 人类肿瘤 WES 分析流程镜像。 |
| `human_tumor_WGS.sif` | `/public/software/VersionHub/biosoft/bin/human_tumor_WGS.sif` | 人类肿瘤 WGS 分析流程镜像。 |
| `md_report.sif` | `/public/software/VersionHub/biosoft/bin/md_report.sif` | Markdown 或报告生成相关镜像。 |
| `mosdepth.sif` | `/public/software/VersionHub/biosoft/bin/mosdepth.sif` | mosdepth 覆盖度统计镜像。 |
| `qiime2.sif` | `/public/software/VersionHub/biosoft/bin/qiime2.sif` | QIIME2 微生物组分析镜像。 |
| `rna_alignment.sif` | `/public/software/VersionHub/biosoft/bin/rna_alignment.sif` | RNA 比对流程镜像。 |

## R 环境与关键 R 包

R 运行入口：

```text
/public/software/VersionHub/R/4.4.2/R
/public/software/VersionHub/R/4.4.2/Rscript
```

涉及 R 包、Bioconductor 包或需要执行 R 脚本的工作流时，环境支持报告应优先强调 Rscript 调用路径：

```text
/public/software/VersionHub/R/4.4.2/Rscript
```

R 包库路径：

```text
/public/software/VersionHub/R/4.4.2/library
```

检测到 R 包总数：457。

| 包 | 版本 | 可执行任务 |
|---|---:|---|
| `Seurat` | 5.3.0 | 单细胞 RNA-seq 标准分析、质控、归一化、降维、聚类、marker 分析。 |
| `SeuratObject` | 5.2.0 | Seurat 单细胞对象数据结构。 |
| `SeuratWrappers` | 0.4.0 | Seurat 扩展接口，支持与 monocle3、fastMNN、velocity 等方法衔接。 |
| `SingleCellExperiment` | 1.28.1 | Bioconductor 单细胞数据对象。 |
| `SingleR` | 2.8.0 | 参考数据库驱动的单细胞类型自动注释。 |
| `celldex` | 1.12.0 | 单细胞注释参考数据库。 |
| `CellChat` | 1.6.1 | 细胞通讯、配体受体互作、通讯网络分析。 |
| `monocle3` | 1.4.26 | 单细胞聚类、差异表达、轨迹分析、拟时序分析。 |
| `BPCells` | 0.3.1 | 大规模单细胞稀疏矩阵处理。 |
| `batchelor` | 1.22.0 | 单细胞批次校正。 |
| `sctransform` | 0.4.2 | 单细胞 UMI 数据方差稳定变换。 |
| `scuttle` | 1.16.0 | 单细胞 RNA-seq 分析工具函数。 |
| `DESeq2` | 1.46.0 | RNA-seq 差异表达分析。 |
| `edgeR` | 4.4.2 | RNA-seq 差异表达分析。 |
| `limma` | 3.62.2 | 表达矩阵线性模型、芯片和组学差异分析。 |
| `sva` | 3.54.0 | 批次效应和 surrogate variable 分析。 |
| `clusterProfiler` | 4.14.6 | GO、KEGG、GSEA 富集分析。 |
| `enrichplot` | 1.26.6 | 富集分析结果可视化。 |
| `fgsea` | 1.32.4 | 快速 GSEA 分析。 |
| `DOSE` | 4.0.1 | Disease Ontology 语义和富集分析。 |
| `GOSemSim` | 2.32.0 | GO 术语语义相似性分析。 |
| `GO.db` | 3.20.0 | Gene Ontology 注释数据库。 |
| `KEGGREST` | 1.46.0 | KEGG REST 资源访问。 |
| `org.Hs.eg.db` | 3.20.0 | 人类基因注释数据库。 |
| `AnnotationDbi` | 1.68.0 | Bioconductor SQLite 注释数据库操作。 |
| `AnnotationHub` | 3.14.0 | Bioconductor 注释资源访问。 |
| `ExperimentHub` | 2.14.0 | Bioconductor 实验数据资源访问。 |
| `biomaRt` | 2.62.1 | Ensembl 和 BioMart 注释查询。 |
| `ChIPseeker` | 1.42.1 | ChIP-seq peak 注释、比较、可视化。 |
| `TxDb.Hsapiens.UCSC.hg19.knownGene` | 3.2.2 | hg19 knownGene 转录本注释。 |
| `GenomicRanges` | 1.58.0 | 基因组区间表示与操作。 |
| `GenomicFeatures` | 1.58.0 | 基因模型查询与 TxDb 构建。 |
| `GenomicAlignments` | 1.42.0 | 短 reads 比对结果表示和处理。 |
| `Rsamtools` | 2.22.0 | BAM、FASTA、BCF、tabix 文件读写。 |
| `Rhtslib` | 3.2.0 | R 中的 HTSlib 支撑库。 |
| `Biostrings` | 2.74.1 | DNA、RNA、蛋白序列处理。 |
| `GenomeInfoDb` | 1.42.3 | 染色体命名和基因组信息处理。 |
| `IRanges` | 2.40.1 | 整数区间基础设施。 |
| `S4Vectors` | 0.44.0 | Bioconductor S4 向量和列表基础设施。 |
| `SummarizedExperiment` | 1.36.0 | 组学矩阵和样本注释容器。 |
| `DelayedArray` | 0.32.0 | 延迟数组计算。 |
| `HDF5Array` | 1.34.0 | HDF5 后端大矩阵处理。 |
| `SparseArray` | 1.6.2 | 高性能稀疏数组表示。 |
| `Matrix` | 1.7-4 | 稀疏和稠密矩阵。 |
| `MatrixGenerics` | 1.18.1 | 矩阵统计泛型函数。 |
| `DNAcopy` | 1.80.0 | DNA copy number 分段分析。 |
| `fastseg` | 1.52.0 | 快速分段算法。 |
| `edmr` | 0.6.4.1 | 经验差异甲基化区域计算。 |
| `methylKit` | 1.32.1 | Bisulfite sequencing DNA 甲基化分析。 |
| `maftools` | 2.22.0 | MAF 突变数据汇总、分析和可视化。 |
| `ComplexHeatmap` | 2.22.0 | 复杂热图绘制。 |
| `EnhancedVolcano` | 1.24.0 | 发表级火山图绘制。 |
| `PCAtools` | 2.18.0 | PCA 分析和可视化。 |
| `FactoMineR` | 2.12 | 多变量探索性数据分析。 |
| `factoextra` | 1.0.7 | 多变量分析结果提取与可视化。 |
| `NMF` | 0.28 | 非负矩阵分解。 |
| `qvalue` | 2.38.0 | FDR q-value 估计。 |
| `ggtree` | 3.14.0 | 系统发育树可视化。 |
| `treeio` | 1.30.0 | 系统发育树输入输出。 |
| `tidytree` | 0.4.6 | tidy 风格系统发育树数据处理。 |
| `ape` | 5.8-1 | 系统发育和进化分析。 |
| `circlize` | 0.4.16 | 环形图和基因组圈图。 |
| `ggplot2` | 4.0.0 | 通用统计绘图。 |
| `ggpubr` | 0.6.1 | 发表级 ggplot 图形。 |
| `ggrepel` | 0.9.6 | 图中文字避让。 |
| `patchwork` | 1.3.2 | 多图拼接。 |
| `pheatmap` | 1.0.13 | 热图绘制。 |
| `plotly` | 4.11.0 | 交互式图形。 |
| `shiny` | 1.11.1 | R 交互式 Web 应用。 |
| `DT` | 0.34.0 | 交互式表格。 |
| `tidyverse` | 2.0.0 | tidyverse 包集合。 |
| `dplyr` | 1.1.4 | 表格数据处理。 |
| `tidyr` | 1.3.1 | 表格整理。 |
| `readr` | 2.1.5 | 矩形文本读取。 |
| `purrr` | 1.1.0 | 函数式编程。 |
| `data.table` | 1.17.8 | 高性能表格处理。 |
| `future` | 1.67.0 | 并行与分布式计算。 |
| `BiocParallel` | 1.40.1 | Bioconductor 并行计算。 |
| `devtools` | 2.4.5 | R 包开发和安装。 |
| `remotes` | 2.5.0 | 远程 R 包安装。 |

## R 包完整索引

下表列出本次检测到的 457 个 R 包名称和版本。标题字段不用于依赖判断，依赖判断应优先匹配包名和版本。

| 包 | 版本 |
|---|---:|
| `AnnotationDbi` | 1.68.0 |
| `AnnotationHub` | 3.14.0 |
| `BH` | 1.87.0-1 |
| `BPCells` | 0.3.1 |
| `Biobase` | 2.66.0 |
| `BiocFileCache` | 2.14.0 |
| `BiocGenerics` | 0.52.0 |
| `BiocIO` | 1.16.0 |
| `BiocManager` | 1.30.26 |
| `BiocNeighbors` | 2.0.1 |
| `BiocParallel` | 1.40.1 |
| `BiocSingular` | 1.22.0 |
| `BiocVersion` | 3.20.0 |
| `Biostrings` | 2.74.1 |
| `Cairo` | 1.6-5 |
| `CellChat` | 1.6.1 |
| `ChIPseeker` | 1.42.1 |
| `ComplexHeatmap` | 2.22.0 |
| `DBI` | 1.2.3 |
| `DDRTree` | 0.1.5 |
| `DESeq2` | 1.46.0 |
| `DNAcopy` | 1.80.0 |
| `DOSE` | 4.0.1 |
| `DT` | 0.34.0 |
| `DelayedArray` | 0.32.0 |
| `DelayedMatrixStats` | 1.28.1 |
| `Deriv` | 4.2.0 |
| `EnhancedVolcano` | 1.24.0 |
| `ExperimentHub` | 2.14.0 |
| `FNN` | 1.1.4.1 |
| `FactoMineR` | 2.12 |
| `Formula` | 1.2-5 |
| `GO.db` | 3.20.0 |
| `GOSemSim` | 2.32.0 |
| `GenomeInfoDb` | 1.42.3 |
| `GenomeInfoDbData` | 1.2.13 |
| `GenomicAlignments` | 1.42.0 |
| `GenomicFeatures` | 1.58.0 |
| `GenomicRanges` | 1.58.0 |
| `GetoptLong` | 1.0.5 |
| `GlobalOptions` | 0.1.2 |
| `HDF5Array` | 1.34.0 |
| `IRanges` | 2.40.1 |
| `KEGGREST` | 1.46.0 |
| `KernSmooth` | 2.23-26 |
| `MASS` | 7.3-65 |
| `Matrix` | 1.7-4 |
| `MatrixGenerics` | 1.18.1 |
| `MatrixModels` | 0.5-4 |
| `NMF` | 0.28 |
| `OpenMx` | 2.21.13 |
| `PCAtools` | 2.18.0 |
| `R.methodsS3` | 1.8.2 |
| `R.oo` | 1.27.1 |
| `R.utils` | 2.13.0 |
| `R6` | 2.6.1 |
| `RANN` | 2.6.2 |
| `RColorBrewer` | 1.1-3 |
| `RCurl` | 1.98-1.17 |
| `ROCR` | 1.0-11 |
| `RSQLite` | 2.4.3 |
| `RSpectra` | 0.16-2 |
| `Rcpp` | 1.1.0 |
| `RcppAnnoy` | 0.0.22 |
| `RcppArmadillo` | 15.0.2-1 |
| `RcppEigen` | 0.3.4.0.2 |
| `RcppHNSW` | 0.6.0 |
| `RcppParallel` | 5.1.11-1 |
| `RcppProgress` | 0.4.2 |
| `RcppTOML` | 0.2.3 |
| `Rdpack` | 2.6.4 |
| `ResidualMatrix` | 1.16.0 |
| `Rhdf5lib` | 1.28.0 |
| `RhpcBLASctl` | 0.23-42 |
| `Rhtslib` | 3.2.0 |
| `Rsamtools` | 2.22.0 |
| `Rtsne` | 0.17 |
| `Rttf2pt1` | 1.3.12 |
| `S4Arrays` | 1.6.0 |
| `S4Vectors` | 0.44.0 |
| `S7` | 0.2.0 |
| `ScaledMatrix` | 1.14.0 |
| `Seurat` | 5.3.0 |
| `SeuratObject` | 5.2.0 |
| `SeuratWrappers` | 0.4.0 |
| `SingleCellExperiment` | 1.28.1 |
| `SingleR` | 2.8.0 |
| `SparseArray` | 1.6.2 |
| `SparseM` | 1.84-2 |
| `SummarizedExperiment` | 1.36.0 |
| `TxDb.Hsapiens.UCSC.hg19.knownGene` | 3.2.2 |
| `UCSC.utils` | 1.2.0 |
| `V8` | 7.0.0 |
| `VGAM` | 1.1-13 |
| `XML` | 3.99-0.19 |
| `XVector` | 0.46.0 |
| `abind` | 1.4-8 |
| `alabaster.base` | 1.6.1 |
| `alabaster.matrix` | 1.6.1 |
| `alabaster.ranges` | 1.6.0 |
| `alabaster.schemas` | 1.6.0 |
| `alabaster.se` | 1.6.0 |
| `annotate` | 1.84.0 |
| `ape` | 5.8-1 |
| `aplot` | 0.2.9 |
| `arrow` | 21.0.0 |
| `ash` | 1.0-15 |
| `askpass` | 1.2.1 |
| `assertthat` | 0.2.1 |
| `assorthead` | 1.0.1 |
| `backports` | 1.5.0 |
| `base64enc` | 0.1-3 |
| `batchelor` | 1.22.0 |
| `bbmle` | 1.0.25.1 |
| `bdsmatrix` | 1.3-7 |
| `beachmat` | 2.22.0 |
| `beeswarm` | 0.4.0 |
| `biglm` | 0.9-3 |
| `biomaRt` | 2.62.1 |
| `bit` | 4.6.0 |
| `bit64` | 4.6.0-1 |
| `bitops` | 1.0-9 |
| `blob` | 1.2.4 |
| `boot` | 1.3-32 |
| `brew` | 1.0-10 |
| `brio` | 1.1.5 |
| `broom` | 1.0.10 |
| `bslib` | 0.9.0 |
| `caTools` | 1.18.3 |
| `cachem` | 1.1.0 |
| `callr` | 3.7.6 |
| `car` | 3.1-3 |
| `carData` | 3.0-5 |
| `celldex` | 1.12.0 |
| `cellranger` | 1.1.0 |
| `circlize` | 0.4.16 |
| `class` | 7.3-23 |
| `classInt` | 0.4-11 |
| `cli` | 3.6.5 |
| `clipr` | 0.8.0 |
| `clue` | 0.3-66 |
| `cluster` | 2.1.8.1 |
| `clusterProfiler` | 4.14.6 |
| `coda` | 0.19-4.1 |
| `codetools` | 0.2-20 |
| `colorspace` | 2.1-1 |
| `commonmark` | 2.0.0 |
| `conflicted` | 1.2.0 |
| `corrplot` | 0.95 |
| `cowplot` | 1.2.0 |
| `cpp11` | 0.5.2 |
| `crayon` | 1.5.3 |
| `credentials` | 2.0.3 |
| `crosstalk` | 1.2.2 |
| `curl` | 7.0.0 |
| `data.table` | 1.17.8 |
| `dbplyr` | 2.5.1 |
| `deldir` | 2.0-4 |
| `dendextend` | 1.19.1 |
| `desc` | 1.4.3 |
| `devtools` | 2.4.5 |
| `diffobj` | 0.3.6 |
| `digest` | 0.6.37 |
| `distributional` | 0.5.0 |
| `doBy` | 4.7.0 |
| `doParallel` | 1.0.17 |
| `dotCall64` | 1.2 |
| `downlit` | 0.4.4 |
| `downloader` | 0.4.1 |
| `dplyr` | 1.1.4 |
| `dqrng` | 0.4.1 |
| `dtplyr` | 1.3.2 |
| `e1071` | 1.7-16 |
| `edgeR` | 4.4.2 |
| `edmr` | 0.6.4.1 |
| `ellipse` | 0.5.0 |
| `ellipsis` | 0.3.2 |
| `emdbook` | 1.3.14 |
| `emmeans` | 2.0.0 |
| `enrichplot` | 1.26.6 |
| `estimability` | 1.5.1 |
| `evaluate` | 1.0.5 |
| `expm` | 1.0-0 |
| `extrafont` | 0.19 |
| `extrafontdb` | 1.0 |
| `factoextra` | 1.0.7 |
| `fansi` | 1.0.6 |
| `farver` | 2.1.2 |
| `fastDummies` | 1.7.5 |
| `fastmap` | 1.2.0 |
| `fastmatch` | 1.1-6 |
| `fastseg` | 1.52.0 |
| `fgsea` | 1.32.4 |
| `filelock` | 1.0.3 |
| `fitdistrplus` | 1.2-4 |
| `flashClust` | 1.01-2 |
| `fontBitstreamVera` | 0.1.1 |
| `fontLiberation` | 0.1.0 |
| `fontawesome` | 0.5.3 |
| `fontquiver` | 0.2.1 |
| `forcats` | 1.0.0 |
| `foreach` | 1.5.2 |
| `formatR` | 1.14 |
| `fs` | 1.6.6 |
| `furrr` | 0.3.1 |
| `futile.logger` | 1.4.3 |
| `futile.options` | 1.0.1 |
| `future` | 1.67.0 |
| `future.apply` | 1.20.0 |
| `gargle` | 1.6.0 |
| `gdtools` | 0.4.3 |
| `genefilter` | 1.88.0 |
| `generics` | 0.1.4 |
| `gert` | 2.1.5 |
| `getopt` | 1.20.4 |
| `ggalluvial` | 0.12.5 |
| `ggalt` | 0.4.0 |
| `ggbeeswarm` | 0.7.2 |
| `ggdist` | 3.3.3 |
| `ggforce` | 0.5.0 |
| `ggfun` | 0.2.0 |
| `ggnetwork` | 0.5.14 |
| `ggnewscale` | 0.5.2 |
| `ggplot2` | 4.0.0 |
| `ggplotify` | 0.1.2 |
| `ggpubr` | 0.6.1 |
| `ggrastr` | 1.0.2 |
| `ggrepel` | 0.9.6 |
| `ggridges` | 0.5.7 |
| `ggsci` | 3.2.0 |
| `ggsignif` | 0.6.4 |
| `ggtangle` | 0.0.7 |
| `ggtree` | 3.14.0 |
| `ggupset` | 0.4.1 |
| `gh` | 1.5.0 |
| `gitcreds` | 0.1.2 |
| `globals` | 0.18.0 |
| `glue` | 1.8.0 |
| `goftest` | 1.2-3 |
| `googledrive` | 2.1.2 |
| `googlesheets4` | 1.1.2 |
| `gplots` | 3.2.0 |
| `gridBase` | 0.4-7 |
| `gridExtra` | 2.3 |
| `gridGraphics` | 0.5-1 |
| `grr` | 0.9.5 |
| `gson` | 0.1.0 |
| `gtable` | 0.3.6 |
| `gtools` | 3.9.5 |
| `gypsum` | 1.2.0 |
| `haven` | 2.5.5 |
| `here` | 1.0.2 |
| `hexbin` | 1.28.5 |
| `highr` | 0.11 |
| `hms` | 1.1.3 |
| `htmltools` | 0.5.8.1 |
| `htmlwidgets` | 1.6.4 |
| `httpuv` | 1.6.16 |
| `httr` | 1.4.7 |
| `httr2` | 1.2.1 |
| `ica` | 1.0-3 |
| `ids` | 1.0.1 |
| `igraph` | 2.1.4 |
| `ini` | 0.3.1 |
| `irlba` | 2.3.5.1 |
| `isoband` | 0.2.7 |
| `iterators` | 1.0.14 |
| `jquerylib` | 0.1.4 |
| `jsonlite` | 2.0.0 |
| `jsonvalidate` | 1.5.0 |
| `kernlab` | 0.9-33 |
| `knitr` | 1.50 |
| `labeling` | 0.4.3 |
| `lambda.r` | 1.2.4 |
| `later` | 1.4.4 |
| `lattice` | 0.22-7 |
| `lazyeval` | 0.2.2 |
| `leaps` | 3.2 |
| `leidenbase` | 0.1.35 |
| `lifecycle` | 1.0.4 |
| `limma` | 3.62.2 |
| `listenv` | 0.9.1 |
| `lme4` | 1.1-37 |
| `lmtest` | 0.9-40 |
| `locfit` | 1.5-9.12 |
| `lubridate` | 1.9.4 |
| `maftools` | 2.22.0 |
| `magrittr` | 2.0.4 |
| `maps` | 3.4.3 |
| `matrixStats` | 1.5.0 |
| `mclust` | 6.1.1 |
| `memoise` | 2.0.1 |
| `methylKit` | 1.32.1 |
| `mgcv` | 1.9-3 |
| `microbenchmark` | 1.5.0 |
| `mime` | 0.13 |
| `miniUI` | 0.1.2 |
| `minqa` | 1.2.8 |
| `mixtools` | 2.0.0.1 |
| `modelr` | 0.1.11 |
| `monocle3` | 1.4.26 |
| `multcompView` | 0.1-10 |
| `mvtnorm` | 1.3-3 |
| `network` | 1.19.0 |
| `nlme` | 3.1-168 |
| `nloptr` | 2.2.1 |
| `nnet` | 7.3-20 |
| `numDeriv` | 2016.8-1.1 |
| `openssl` | 2.3.3 |
| `optparse` | 1.7.5 |
| `org.Hs.eg.db` | 3.20.0 |
| `otel` | 0.2.0 |
| `parallelly` | 1.45.1 |
| `patchwork` | 1.3.2 |
| `pbapply` | 1.7-4 |
| `pbkrtest` | 0.5.5 |
| `pbmcapply` | 1.5.1 |
| `pheatmap` | 1.0.13 |
| `pillar` | 1.11.1 |
| `pkgbuild` | 1.4.8 |
| `pkgconfig` | 2.0.3 |
| `pkgdown` | 2.1.3 |
| `pkgload` | 1.4.0 |
| `plogr` | 0.2.0 |
| `plotly` | 4.11.0 |
| `plotrix` | 3.8-4 |
| `plyr` | 1.8.9 |
| `png` | 0.1-8 |
| `polyclip` | 1.10-7 |
| `polynom` | 1.4-1 |
| `praise` | 1.0.0 |
| `prettyunits` | 1.2.0 |
| `processx` | 3.8.6 |
| `profvis` | 0.4.0 |
| `progress` | 1.2.3 |
| `progressr` | 0.16.0 |
| `proj4` | 1.0-15 |
| `promises` | 1.3.3 |
| `proxy` | 0.4-27 |
| `ps` | 1.9.1 |
| `pscl` | 1.5.9 |
| `purrr` | 1.1.0 |
| `quadprog` | 1.5-8 |
| `quantreg` | 6.1 |
| `qvalue` | 2.38.0 |
| `rJava` | 1.0-11 |
| `ragg` | 1.5.0 |
| `rappdirs` | 0.3.3 |
| `rbibutils` | 2.3 |
| `rcmdcheck` | 1.4.0 |
| `readr` | 2.1.5 |
| `readxl` | 1.4.5 |
| `reformulas` | 0.4.1 |
| `registry` | 0.5-1 |
| `rematch` | 2.0.0 |
| `rematch2` | 2.1.2 |
| `remotes` | 2.5.0 |
| `reprex` | 2.1.1 |
| `reshape2` | 1.4.4 |
| `restfulr` | 0.0.16 |
| `reticulate` | 1.43.0 |
| `rhdf5` | 2.50.2 |
| `rhdf5filters` | 1.16.0 |
| `rjson` | 0.2.23 |
| `rlang` | 1.1.6 |
| `rmarkdown` | 2.29 |
| `rngtools` | 1.5.2 |
| `roxygen2` | 7.3.3 |
| `rprojroot` | 2.1.1 |
| `rsample` | 1.3.1 |
| `rstatix` | 0.7.2 |
| `rstudioapi` | 0.17.1 |
| `rsvd` | 1.0.5 |
| `rtracklayer` | 1.66.0 |
| `rversions` | 2.1.2 |
| `rvest` | 1.0.5 |
| `s2` | 1.1.9 |
| `sass` | 0.4.10 |
| `scales` | 1.4.0 |
| `scattermore` | 1.2 |
| `scatterpie` | 0.2.6 |
| `scatterplot3d` | 0.3-44 |
| `sctransform` | 0.4.2 |
| `scuttle` | 1.16.0 |
| `segmented` | 2.1-4 |
| `selectr` | 0.4-2 |
| `sessioninfo` | 1.2.3 |
| `sf` | 1.0-21 |
| `shape` | 1.4.6.1 |
| `shiny` | 1.11.1 |
| `sitmo` | 2.0.2 |
| `slam` | 0.1-55 |
| `slider` | 0.3.2 |
| `sna` | 2.8 |
| `snow` | 0.4-4 |
| `sourcetools` | 0.1.7-1 |
| `sp` | 2.2-0 |
| `spData` | 2.3.4 |
| `spam` | 2.11-1 |
| `sparseMatrixStats` | 1.18.0 |
| `spatstat.data` | 3.1-8 |
| `spatstat.explore` | 3.5-2 |
| `spatstat.geom` | 3.5-0 |
| `spatstat.random` | 3.4-1 |
| `spatstat.sparse` | 3.1-0 |
| `spatstat.univar` | 3.1-4 |
| `spatstat.utils` | 3.1-5 |
| `spdep` | 1.4-1 |
| `speedglm` | 0.3-5 |
| `statmod` | 1.5.0 |
| `statnet.common` | 4.12.0 |
| `stringi` | 1.8.7 |
| `stringr` | 1.5.2 |
| `survival` | 3.8-3 |
| `sva` | 3.54.0 |
| `svglite` | 2.2.1 |
| `sys` | 3.4.3 |
| `systemfonts` | 1.2.3 |
| `tensor` | 1.5.1 |
| `terra` | 1.8-42 |
| `testthat` | 3.2.3 |
| `textshaping` | 1.0.3 |
| `tibble` | 3.3.0 |
| `tidyr` | 1.3.1 |
| `tidyselect` | 1.2.1 |
| `tidytree` | 0.4.6 |
| `tidyverse` | 2.0.0 |
| `timechange` | 0.3.0 |
| `tinytex` | 0.57 |
| `treeio` | 1.30.0 |
| `tweenr` | 2.0.3 |
| `tzdb` | 0.5.0 |
| `units` | 0.8-7 |
| `urlchecker` | 1.0.1 |
| `usethis` | 3.2.1 |
| `utf8` | 1.2.6 |
| `uuid` | 1.2-1 |
| `uwot` | 0.2.3 |
| `vctrs` | 0.6.5 |
| `vipor` | 0.4.7 |
| `viridis` | 0.6.5 |
| `viridisLite` | 0.4.2 |
| `vroom` | 1.6.5 |
| `waldo` | 0.6.2 |
| `warp` | 0.2.1 |
| `whisker` | 0.4.1 |
| `withr` | 3.0.2 |
| `wk` | 0.9.4 |
| `xfun` | 0.53 |
| `xml2` | 1.4.0 |
| `xopen` | 1.0.1 |
| `xtable` | 1.8-4 |
| `yaml` | 2.3.10 |
| `yulab.utils` | 0.2.1 |
| `zip` | 2.3.3 |
| `zlibbioc` | 1.52.0 |
| `zoo` | 1.8-14 |

## 论文任务到依赖的匹配表

| 论文任务类型 | 支持状态 | 可匹配依赖 |
|---|---|---|
| FASTQ 质控、过滤、接头去除 | 支持 | `fastp`, `seqkit`, `seqtk` |
| WGS 或 WES reads 比对 | 支持 | `bwa`, `bowtie2`, `samtools`, `sambamba` |
| RNA-seq reads 比对 | 支持 | `bowtie2`, `bwa`, `samtools`, `rna_alignment.sif` |
| BAM 排序、索引、过滤、去重复 | 支持 | `samtools`, `sambamba`, `picard`, `fgbio` |
| Germline SNV 和 Indel 检测 | 支持 | `gatk`, `bcftools`, `freebayes` in `pgcgap-1` |
| Somatic SNV 和 Indel 检测 | 支持 | `gatk`, `vardict-java`, `bcftools`, `human_tumor_WES.sif`, `human_tumor_WGS.sif` |
| VCF 过滤、合并、统计、索引 | 支持 | `bcftools`, `tabix`, `bgzip`, `vcf_filter.py` |
| CNV 检测 | 支持 | `cnvkit`, `DNAcopy`, `fastseg`, `cnvkit` Conda env |
| 结构变异检测 | 支持 | `manta`, `svfilter.py` |
| 覆盖度和测序深度统计 | 支持 | `mosdepth`, `pandepth`, `bamdst`, `mosdepth.sif` |
| MSI 检测 | 支持 | `msisensor2` |
| UMI 处理 | 支持 | `fgbio`, `extractUmisFromBam.py`, `umi_qc.py` |
| RNA-seq 差异表达 | 支持 | `DESeq2`, `edgeR`, `limma` |
| 批次效应校正 | 支持 | `sva`, `batchelor`, `limma` |
| GO、KEGG、GSEA 富集分析 | 支持 | `clusterProfiler`, `fgsea`, `enrichplot`, `DOSE`, `GO.db`, `KEGGREST`, `org.Hs.eg.db` |
| 单细胞 RNA-seq 标准分析 | 支持 | `Seurat`, `SeuratObject`, `SingleCellExperiment`, `scuttle`, `sctransform`, `BPCells` |
| 单细胞细胞类型注释 | 支持 | `SingleR`, `celldex`, `AnnotationHub`, `ExperimentHub` |
| 单细胞轨迹和拟时序分析 | 支持 | `monocle3`, `SeuratWrappers` |
| 单细胞细胞通讯分析 | 支持 | `CellChat` |
| ChIP-seq peak 注释 | 支持 | `ChIPseeker`, `GenomicRanges`, `GenomicFeatures`, `TxDb.Hsapiens.UCSC.hg19.knownGene` |
| 甲基化 reads 比对 | 支持 | `BSMAPz`, `bsmap` Conda env |
| 差异甲基化分析 | 支持 | `methdiff.py`, `methratio.py`, `methylKit`, `edmr` |
| MAF 突变谱分析 | 支持 | `maftools` |
| 原核基因组组装 | 支持 | `spades` in `pgcgap-1`, `abyss`, `canu` |
| 原核基因组注释 | 支持 | `pgcgap`, `barrnap`, `aragorn`, `abricate` |
| 原核比较基因组 | 支持 | `pgcgap`, `blast`, `diamond`, `mmseqs2`, `mash`, `cd-hit` |
| 系统发育树构建 | 支持 | `FastTree`, `FastTreeMP`, `mafft`, `muscle`, `ape`, `ggtree`, `treeio` |
| 微生物组 QIIME2 分析 | 支持但需确认镜像入口 | `qiime2.sif`, `apptainer` |
| 工作流编排 | 支持 | `snakemake`, `parallel`, `drmaa` |
| 容器化流程执行 | 支持 | `apptainer`, `.sif` 镜像文件 |

## 依赖判断建议

1. 判断命令行软件时，优先检查 `/public/software/VersionHub/biosoft/bin` 是否存在同名可执行文件。
2. 判断 Conda 环境时，优先检查 `/public/software/VersionHub/biosoft/miniconda3/envs/<env_name>/conda-meta` 是否存在包元数据。
3. 判断 R 包时，优先检查 `/public/software/VersionHub/R/4.4.2/library/<package_name>/DESCRIPTION`。
4. 遇到 `picard`、`gatk`、`fgbio` 这类 Java 工具时，同时检查命令入口和 jar 文件。
5. 遇到 WES、WGS、RNA alignment、QIIME2 这类整套流程时，可以同时匹配 `.sif` 容器镜像和 `apptainer`。
6. `cnvkit-1` 和 `picard` Conda 环境目录缺少可确认的 `conda-meta` 包元数据，依赖判断时应优先使用 `biosoft/bin` 中的命令或 jar 文件。
7. 对论文中只写方法名、不写软件名的场景，可以按任务匹配表映射到候选依赖，再检查是否有具体命令、Conda 环境或 R 包。
