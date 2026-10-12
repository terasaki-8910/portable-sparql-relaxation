# Third-party notices

`LICENSE` (MIT) applies to the authors' own code and files. The components
listed here come from third parties and remain under their own licences.

## 1. Conference v3.0 populated datasets

- **Files**: `data/datasets.tar.gz`, extracted by `scripts/setup_data.py` into:

| Extracted file | Path in the upstream repository | SHA-256 |
|---|---|---|
| `data/datasets/cmt_100.ttl` | `populated_datasets/data_100/cmt_100.ttl` | `efb7e8c7f377ef2bd70c1a855945fe093ccd78f986c3055c1fcf9a87c5ea900b` |
| `data/datasets/cmt_eswc.ttl` | `populated_datasets/eswc/cmt_eswc.ttl` | `0a7266f947fee4c728a578f891e4cf9745e33fb4d68bdce29fb02b484fe18f79` |
| `data/datasets/confOf_100.ttl` | `populated_datasets/data_100/confOf_100.ttl` | `714650f583fe4df9d199aaecfc1e9092e1d138a4e79d7b9e2bb68f6013bcfed2` |
| `data/datasets/confOf_eswc.ttl` | `populated_datasets/eswc/confOf_eswc.ttl` | `9cab64d89360dfee2a3a353e46281453946d425a3ec43546e5f2d40709458397` |
| `data/datasets/conference_100.ttl` | `populated_datasets/data_100/conference_100.ttl` | `92bb1dad519a35a74d9430e4dddaf40397329acdcd22866b225a37d2e7cf8a5a` |
| `data/datasets/conference_eswc.ttl` | `populated_datasets/eswc/conference_eswc.ttl` | `09640354e338ee254e2af3ed1d9cffc2c75bb49d7a92a47c2e10da90d0fa22d4` |
| `data/datasets/edas_100.ttl` | `populated_datasets/data_100/edas_100.ttl` | `edde61de152ef35e85f98b0b259ea06be635f91fb2fc07b4859fe2e9bfe037bf` |
| `data/datasets/edas_eswc.ttl` | `populated_datasets/eswc/edas_eswc.ttl` | `5c02be548fee2ed62c269bfcc894a069d2ba970c1e76858f11dc70d4311966d2` |
| `data/datasets/ekaw_100.ttl` | `populated_datasets/data_100/ekaw_100.ttl` | `68892fab8fbf81c1a79125189fb2cc06dfb344b71c7bd0f41c5c32ff053161a9` |
| `data/datasets/ekaw_eswc.ttl` | `populated_datasets/eswc/ekaw_eswc.ttl` | `9bc91a61a626b54c8d05511b4d8e454b8a3f189523c46815009919975c95249f` |

- **Origin**: https://framagit.org/IRIT_UT2J/conference-dataset-population, commit `24b9f1af82791fb65e27fd682b64c804dc703fe4`
  (folders `populated_datasets/data_100/` and `populated_datasets/eswc/`).
  Unmodified copies. `scripts/fetch_data.py` downloads the same files from
  that commit and checks them against the SHA-256 values above.
- **Reference**: Élodie Thiéblin, Cássia Trojahn. *Conference v3.0: A Populated
  Version of the Conference Dataset.* ISWC 2019 Satellite Tracks (Posters &
  Demonstrations), CEUR Workshop Proceedings, Vol-2456, 2019.
- **Licence**: GNU Lesser General Public License v2.1 or later
  (LGPL-2.1-or-later), the licence of the upstream repository. The licence text
  is in `LICENSES/LGPL-2.1.txt`.

## 2. EDOAL alignments of the 20 Conference pairs

- **Files**: `data/alignment/<pair>/alignment/<pair>.edoal` (20 files).
- **Origin**: same upstream repository, `alignments/Query_rewriting/<pair>.edoal`;
  unmodified copies.
- **Licence**: LGPL-2.1-or-later (upstream repository licence).

## 3. Conference source queries

- **Files**: `data/alignment/<pair>/queries/q_*.sparql` (1038 files).
- **Origin**: same upstream repository, folder `queries_1-n/<source
  ontology>/`. 1036 files are unmodified copies of the upstream
  file with the same name. The remaining 2 (`data/alignment/cmt-conference/queries/q_0.sparql`, `data/alignment/confOf-cmt/queries/q_1.sparql`) differ from their upstream counterparts only in whitespace.
- **Licence**: LGPL-2.1-or-later (upstream repository licence).

The other query files (29 files `data/alignment/*/queries/query_*.sparql`
and the Manual 90 files `data/alignment/*/queries/relaxation/*.sparql`) are the
authors' own.

## 4. OntoFarm ontologies

- **Files**: `data/datasets/{cmt,confOf,conference,edas,ekaw}.schema.owl`.
- **Origin**: the cmt, confOf, conference, edas and ekaw ontologies (schema
  only, no instances) of the OntoFarm collection, as used in the OAEI
  Conference track.
- **Citation request**: users of OntoFarm are asked to cite
  - Ondřej Zamazal, Vojtěch Svátek. *The Ten-Year OntoFarm and its
    Fertilization within the Onto-Sphere.* Journal of Web Semantics 43, 2017.
  - Ondřej Šváb, Vojtěch Svátek, Petr Berka, Dušan Rak, Petr Tomášek.
    *OntoFarm: Towards an Experimental Collection of Parallel Ontologies.*
    Poster, ISWC 2005.

## 5. Java libraries

### 5.1 Inside `build/libs/sparql-translator-complex-alignment.jar`

The jar is the unmodified output of `./gradlew build` (see `build.gradle`): the
authors' classes (`sparql_parser_java`, `sparql_serializer_java`, MIT) plus the
runtime dependencies Apache Jena ARQ 4.10.0, Gson 2.10.1 and SLF4J Simple 2.0.9
and their transitive dependencies. Components as recorded in the jar
(`META-INF/DEPENDENCIES`, versions corrected from `META-INF/maven/**/pom.properties`):

| Component | Maven coordinates | Version | Licence |
|---|---|---|---|
| Titanium JSON-LD 1.1 (JRE11) | `com.apicatalog:titanium-json-ld` | 1.3.2 | Apache License, Version 2.0 |
| Jackson-annotations | `com.fasterxml.jackson.core:jackson-annotations` | 2.15.3 | The Apache Software License, Version 2.0 |
| Jackson-core | `com.fasterxml.jackson.core:jackson-core` | 2.15.3 | The Apache Software License, Version 2.0 |
| jackson-databind | `com.fasterxml.jackson.core:jackson-databind` | 2.15.3 | The Apache Software License, Version 2.0 |
| dexx | `com.github.andrewoma.dexx:collection` | 0.7 | MIT License |
| Caffeine cache | `com.github.ben-manes.caffeine:caffeine` | 3.1.8 | Apache License, Version 2.0 |
| JSONLD Java :: Core | `com.github.jsonld-java:jsonld-java` | 0.13.4 | Revised BSD License |
| Gson | `com.google.code.gson:gson` | 2.10.1 | Apache-2.0 |
| error-prone annotations | `com.google.errorprone:error_prone_annotations` | 2.21.1 | Apache 2.0 |
| Protocol Buffers [Core] | `com.google.protobuf:protobuf-java` | 3.24.3 | BSD-3-Clause |
| Apache Commons CLI | `commons-cli:commons-cli` | 1.5.0 | Apache License, Version 2.0 |
| Apache Commons Codec | `commons-codec:commons-codec` | 1.16.0 | Apache-2.0 |
| Apache Commons IO | `commons-io:commons-io` | 2.14.0 | Apache-2.0 |
| Apache Commons Collections | `org.apache.commons:commons-collections4` | 4.4 | Apache License, Version 2.0 |
| Apache Commons Compress | `org.apache.commons:commons-compress` | 1.24.0 | Apache-2.0 |
| Apache Commons CSV | `org.apache.commons:commons-csv` | 1.10.0 | Apache-2.0 |
| Apache Commons Lang | `org.apache.commons:commons-lang3` | 3.13.0 | Apache-2.0 |
| Apache HttpClient | `org.apache.httpcomponents:httpclient` | 4.5.14 | Apache License, Version 2.0 |
| Apache HttpClient Cache | `org.apache.httpcomponents:httpclient-cache` | 4.5.14 | Apache License, Version 2.0 |
| Apache HttpCore | `org.apache.httpcomponents:httpcore` | 4.4.16 | Apache License, Version 2.0 |
| Apache Jena - ARQ | `org.apache.jena:jena-arq` | 4.10.0 | Apache License, Version 2.0 |
| Apache Jena - Base | `org.apache.jena:jena-base` | 4.10.0 | The Apache Software License, Version 2.0 |
| Apache Jena - Core | `org.apache.jena:jena-core` | 4.10.0 | The Apache Software License, Version 2.0 |
| Apache Jena - IRI | `org.apache.jena:jena-iri` | 4.10.0 | The Apache Software License, Version 2.0 |
| Apache Thrift | `org.apache.thrift:libthrift` | 0.19.0 | The Apache Software License, Version 2.0 |
| Checker Qual | `org.checkerframework:checker-qual` | 3.37.0 | The MIT License |
| JSON-P Default Provider | `org.glassfish:jakarta.json` | 2.0.1 | Eclipse Public License 2.0; GNU General Public License, version 2 with the GNU Classpath Exception |
| org.roaringbitmap:RoaringBitmap | `org.roaringbitmap:RoaringBitmap` | 1.0.0 | Apache 2 |
| JCL 1.2 implemented over SLF4J | `org.slf4j:jcl-over-slf4j` | 1.7.36 | Apache License, Version 2.0 |
| SLF4J API Module | `org.slf4j:slf4j-api` | 2.0.9 | MIT License |
| SLF4J Simple Provider | `org.slf4j:slf4j-simple` | 2.0.9 | MIT License |

The jar also carries `mozilla/public-suffix-list.txt` (Mozilla Public Suffix
List, MPL-2.0, bundled by Apache HttpClient). Licence texts included in the jar:
`META-INF/LICENSE` (Apache-2.0), `META-INF/LICENSE.txt` (MIT, SLF4J),
`META-INF/LICENSE.md` and `META-INF/NOTICE.md` (EPL-2.0, Jakarta JSON-P),
`META-INF/NOTICE`, `META-INF/NOTICE.txt`, `META-INF/FastDoubleParser-LICENSE`,
`META-INF/bigint-LICENSE`.

### 5.2 `lib/jena.jar`, `lib/arq.jar`, `lib/gson.jar`

Apache Jena Core 2.11.0 and Apache Jena ARQ 2.11.0 (Apache-2.0, The Apache
Software Foundation) and Google Gson 2.2.4 (Apache-2.0). The Apache-2.0 text is
in `LICENSES/Apache-2.0.txt`; `jena.jar` and `arq.jar` also carry their own
`META-INF/LICENSE` and `META-INF/NOTICE`, while `gson.jar` carries neither.
They are shipped only
because `modules/translator_adapter.py` checks that these three files exist;
no code in this artifact puts them on a class path. Each jar contains its own
`META-INF/LICENSE`.

### 5.3 Gradle wrapper

`gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.jar`: Gradle wrapper,
Apache-2.0. Running Gradle downloads Gradle 9.2.0 and the Maven Central
dependencies above.

## 6. Not included: baseline translator

The comparison baseline (`baseline_*` columns of Experiment 1) is the SPARQL
query translator of Thiéblin et al. (*Rewriting SELECT SPARQL Queries from 1:n
Complex Correspondences*, Ontology Matching workshop 2016, CEUR-WS Vol-1766),
an extension of the INRIA Alignment API, distributed under the LGPL. It is not
redistributed here. `baseline_compare_generate_all_pairs_results.py` looks for
`SparqlTranslator.jar` and its `lib/` folder in `baseline/thieblin-sparql-translator/jar utiles/`.

## 8. Gradle build plugin

`settings.gradle` applies `org.gradle.toolchains.foojay-resolver-convention`
version 0.8.0 (Apache-2.0, Gradle Inc.). It is not bundled: Gradle downloads it
from the Gradle Plugin Portal on the first build, together with Gradle 9.2.0 and
the Maven Central dependencies declared in `build.gradle`.
