# M10 RDS 读取验收

- 结果：未通过
- 报告 SHA-256：`d8df549b52880507fd9c7164ee39a59b61e6151bec3627077513a5675bae64bb`

```json
{
  "corpus_equal": true,
  "manifests_accepted": true,
  "mismatches": [
    {
      "case_id": "acq-aglaea-01",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:6590:tab:0000:ac842beaa32d:0000",
        "mihoyo_wiki:6885:tab:0000:5dd2af6f7ddc:0000",
        "mihoyo_wiki:4440:module:21:a7245419672e:0004",
        "mihoyo_wiki:4727:tab:0000:a9ce6326b1a9:0000",
        "mihoyo_wiki:4440:module:11:49a6dbd0d442:0000"
      ],
      "sqlite": [
        "mihoyo_wiki:6885:tab:0000:5dd2af6f7ddc:0000",
        "mihoyo_wiki:6590:tab:0000:ac842beaa32d:0000",
        "mihoyo_wiki:4440:module:21:a7245419672e:0004",
        "mihoyo_wiki:4440:module:11:49a6dbd0d442:0000",
        "miyoushe:61534034:body:1b8e937a72aa:0000"
      ]
    },
    {
      "case_id": "acq-aglaea-01",
      "field": "citation_ids",
      "postgres": [
        "mihoyo_wiki:6590:tab:0000:ac842beaa32d:0000"
      ],
      "sqlite": [
        "mihoyo_wiki:6885:tab:0000:5dd2af6f7ddc:0000"
      ]
    },
    {
      "case_id": "acq-article-01",
      "field": "top5_evidence_ids",
      "postgres": [
        "miyoushe:77507239:body:9049e59b25df:0000",
        "miyoushe:77670698:body:a0913e5cceae:0000",
        "miyoushe:77536395:body:05668b5a98df:0000",
        "miyoushe:77649744:body:6ed2bdce825e:0000",
        "miyoushe:77461137:body:75f3eba6275f:0000"
      ],
      "sqlite": [
        "miyoushe:77507239:body:9049e59b25df:0000",
        "miyoushe:77670698:body:a0913e5cceae:0000",
        "miyoushe:77649744:body:6ed2bdce825e:0000",
        "miyoushe:77536395:body:05668b5a98df:0000",
        "miyoushe:77461137:body:75f3eba6275f:0000"
      ]
    },
    {
      "case_id": "desc-aglaea-01",
      "field": "classification",
      "postgres": "ranking_miss",
      "sqlite": "passed"
    },
    {
      "case_id": "desc-aglaea-01",
      "field": "correct",
      "postgres": false,
      "sqlite": true
    },
    {
      "case_id": "desc-aglaea-01",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:4440:module:21:a7245419672e:0004",
        "mihoyo_wiki:4440:module:11:49a6dbd0d442:0000",
        "mihoyo_wiki:4687:tab:0000:db03032893c4:0037",
        "mihoyo_wiki:5149:tab:0000:e8befba003eb:0003",
        "mihoyo_wiki:5460:tab:0000:b87e3d85848c:0003"
      ],
      "sqlite": [
        "mihoyo_wiki:4440:module:21:a7245419672e:0004",
        "mihoyo_wiki:6885:tab:0000:5dd2af6f7ddc:0000",
        "mihoyo_wiki:4440:module:11:49a6dbd0d442:0000",
        "miyoushe:61534034:body:1b8e937a72aa:0000",
        "mihoyo_wiki:4687:tab:0000:db03032893c4:0037"
      ]
    },
    {
      "case_id": "desc-aglaea-02",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:4440:module:21:a7245419672e:0004",
        "mihoyo_wiki:4440:module:11:49a6dbd0d442:0000",
        "mihoyo_wiki:5283:tab:0000:9da3d352f201:0014",
        "mihoyo_wiki:4687:tab:0000:db03032893c4:0037",
        "mihoyo_wiki:5149:tab:0000:e8befba003eb:0003"
      ],
      "sqlite": [
        "mihoyo_wiki:4440:module:21:a7245419672e:0004",
        "mihoyo_wiki:4440:module:11:49a6dbd0d442:0000",
        "mihoyo_wiki:4687:tab:0000:db03032893c4:0037",
        "mihoyo_wiki:5283:tab:0000:9da3d352f201:0014",
        "mihoyo_wiki:5506:tab:0000:d1aaad6ccac1:0015"
      ]
    },
    {
      "case_id": "desc-himeko-01",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:407:module:11:e9ed5e7b915e:0000",
        "mihoyo_wiki:7484:module:11:e7eb585da54b:0000",
        "mihoyo_wiki:7484:module:13:9a3cbb7808ac:0003",
        "mihoyo_wiki:407:module:20:2844b02362ae:0001",
        "mihoyo_wiki:7484:module:14:f89122bb0354:0001"
      ],
      "sqlite": [
        "mihoyo_wiki:407:module:11:e9ed5e7b915e:0000",
        "mihoyo_wiki:7484:module:11:e7eb585da54b:0000",
        "mihoyo_wiki:7484:module:19:f38ee6fadbbf:0000",
        "mihoyo_wiki:407:module:20:2844b02362ae:0001",
        "mihoyo_wiki:7484:module:14:f89122bb0354:0001"
      ]
    },
    {
      "case_id": "desc-himeko-02",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:7484:module:11:e7eb585da54b:0000",
        "mihoyo_wiki:407:module:11:e9ed5e7b915e:0000",
        "mihoyo_wiki:7448:tab:0000:29c8603fe304:0010",
        "mihoyo_wiki:7484:module:13:9a3cbb7808ac:0003",
        "mihoyo_wiki:396:tab:0000:95802b2bed68:0004"
      ],
      "sqlite": [
        "mihoyo_wiki:7484:module:11:e7eb585da54b:0000",
        "mihoyo_wiki:407:module:11:e9ed5e7b915e:0000",
        "mihoyo_wiki:396:tab:0000:95802b2bed68:0004",
        "mihoyo_wiki:7937:tab:0000:40a2ecd2cae9:0006",
        "mihoyo_wiki:4386:tab:0000:8653e97e2467:0001"
      ]
    },
    {
      "case_id": "desc-himeko-05",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:7484:module:19:9481455e90cd:0002",
        "mihoyo_wiki:7928:tab:0000:faf36daadff4:0000",
        "mihoyo_wiki:7928:tab:0000:8afe2521bc45:0001",
        "mihoyo_wiki:406:module:20:252e72d2d1af:0001",
        "mihoyo_wiki:7934:tab:0000:2b23bf5f6d49:0024"
      ],
      "sqlite": [
        "mihoyo_wiki:7484:module:19:9481455e90cd:0002",
        "mihoyo_wiki:7928:tab:0000:faf36daadff4:0000",
        "mihoyo_wiki:7928:tab:0000:8afe2521bc45:0001",
        "mihoyo_wiki:406:module:20:252e72d2d1af:0001",
        "mihoyo_wiki:7928:tab:0000:d79be3b6bd57:0005"
      ]
    },
    {
      "case_id": "desc-himeko-06",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:7484:module:19:9481455e90cd:0002",
        "mihoyo_wiki:7182:tab:0000:580cbd1d086d:0019",
        "mihoyo_wiki:6918:tab:0000:6c012ff81b89:0000",
        "mihoyo_wiki:7763:tab:0000:41260cc931ad:0017",
        "mihoyo_wiki:7178:tab:0000:27c9989ef6f8:0022"
      ],
      "sqlite": [
        "mihoyo_wiki:7484:module:19:9481455e90cd:0002",
        "mihoyo_wiki:6918:tab:0000:6c012ff81b89:0000",
        "mihoyo_wiki:7182:tab:0000:580cbd1d086d:0019",
        "mihoyo_wiki:7763:tab:0000:41260cc931ad:0017",
        "mihoyo_wiki:7178:tab:0000:27c9989ef6f8:0022"
      ]
    },
    {
      "case_id": "desc-himeko-07",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:7484:module:20:afb85eae0887:0005",
        "mihoyo_wiki:7484:module:19:22aaa00baf7e:0004",
        "mihoyo_wiki:4544:tab:0000:d3db9af3cae3:0007",
        "mihoyo_wiki:1085:module:19:59b8410475fb:0000",
        "mihoyo_wiki:7476:tab:0000:c97c2f5bb619:0029"
      ],
      "sqlite": [
        "mihoyo_wiki:7484:module:20:afb85eae0887:0005",
        "mihoyo_wiki:7484:module:19:22aaa00baf7e:0004",
        "mihoyo_wiki:1085:module:19:59b8410475fb:0000",
        "mihoyo_wiki:7476:tab:0000:c97c2f5bb619:0029",
        "mihoyo_wiki:4544:tab:0000:d3db9af3cae3:0007"
      ]
    },
    {
      "case_id": "desc-himeko-09",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:7928:tab:0000:faf36daadff4:0000",
        "mihoyo_wiki:7934:tab:0000:73d919eba870:0017",
        "mihoyo_wiki:7928:tab:0000:8afe2521bc45:0001",
        "mihoyo_wiki:7484:module:20:afb85eae0887:0005",
        "mihoyo_wiki:7928:tab:0000:b83d422b809d:0003"
      ],
      "sqlite": [
        "mihoyo_wiki:7928:tab:0000:faf36daadff4:0000",
        "mihoyo_wiki:7928:tab:0000:8afe2521bc45:0001",
        "mihoyo_wiki:7934:tab:0000:73d919eba870:0017",
        "mihoyo_wiki:7484:module:20:afb85eae0887:0005",
        "mihoyo_wiki:7928:tab:0000:d79be3b6bd57:0005"
      ]
    },
    {
      "case_id": "desc-quest-01",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:7181:tab:0000:c2e4f37cf6c3:0000",
        "mihoyo_wiki:7181:tab:0000:c59d10891904:0014",
        "mihoyo_wiki:7121:tab:0000:f7ed73f8f24a:0000",
        "mihoyo_wiki:7810:tab:0000:ac4ba565c069:0001",
        "mihoyo_wiki:7181:tab:0000:78b48a721213:0001"
      ],
      "sqlite": [
        "mihoyo_wiki:7181:tab:0000:c2e4f37cf6c3:0000",
        "mihoyo_wiki:7181:tab:0000:c59d10891904:0014",
        "mihoyo_wiki:7181:tab:0000:78b48a721213:0001",
        "mihoyo_wiki:7810:tab:0000:ac4ba565c069:0001",
        "mihoyo_wiki:7181:tab:0000:eb5eececb610:0003"
      ]
    },
    {
      "case_id": "desc-quest-02",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:7181:tab:0000:c2e4f37cf6c3:0000",
        "mihoyo_wiki:7181:tab:0000:c59d10891904:0014",
        "mihoyo_wiki:7121:tab:0000:f7ed73f8f24a:0000",
        "mihoyo_wiki:7810:tab:0000:ac4ba565c069:0001",
        "mihoyo_wiki:7181:tab:0000:78b48a721213:0001"
      ],
      "sqlite": [
        "mihoyo_wiki:7181:tab:0000:c2e4f37cf6c3:0000",
        "mihoyo_wiki:7181:tab:0000:c59d10891904:0014",
        "mihoyo_wiki:7181:tab:0000:78b48a721213:0001",
        "mihoyo_wiki:7810:tab:0000:ac4ba565c069:0001",
        "mihoyo_wiki:7181:tab:0000:1bdeb7b6f17d:0002"
      ]
    },
    {
      "case_id": "desc-quest-05",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:7181:tab:0000:9884e3ae0c05:0006",
        "mihoyo_wiki:1298:module:19:599c88714345:0000",
        "mihoyo_wiki:7937:tab:0000:de9a7db9eaa6:0019",
        "mihoyo_wiki:1214:module:19:f21f9bc79aa6:0000",
        "mihoyo_wiki:1655:tab:0000:8def827018bb:0025"
      ],
      "sqlite": [
        "mihoyo_wiki:7181:tab:0000:9884e3ae0c05:0006",
        "mihoyo_wiki:1298:module:19:599c88714345:0000",
        "mihoyo_wiki:7937:tab:0000:de9a7db9eaa6:0019",
        "mihoyo_wiki:1655:tab:0000:8def827018bb:0025",
        "mihoyo_wiki:1214:module:19:f21f9bc79aa6:0000"
      ]
    },
    {
      "case_id": "desc-quest-06",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:2681:tab:0000:b56e21411bfb:0006",
        "mihoyo_wiki:1970:tab:0000:04ae5cc4796b:0003",
        "mihoyo_wiki:2923:tab:0000:5b0052e4da56:0000",
        "mihoyo_wiki:3253:tab:0000:68d5b20e36fe:0000",
        "mihoyo_wiki:4347:tab:0000:d09b04448506:0000"
      ],
      "sqlite": [
        "mihoyo_wiki:2681:tab:0000:b56e21411bfb:0006",
        "mihoyo_wiki:1970:tab:0000:53cc1c0f225f:0000",
        "mihoyo_wiki:4075:tab:0000:591875bea613:0047",
        "mihoyo_wiki:3698:tab:0000:87f508713e9d:0024",
        "mihoyo_wiki:3975:tab:0000:8f5ce992bee5:0000"
      ]
    },
    {
      "case_id": "desc-quest-08",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:6814:module:11:f607ae7b5a2d:0000",
        "mihoyo_wiki:7181:tab:0000:3cf96d273aa7:0013",
        "miyoushe:74155917:body:711fe83fbb5c:0000",
        "mihoyo_wiki:7656:tab:0000:c5d758498a72:0015",
        "mihoyo_wiki:7180:tab:0000:3cdbd8ae2ae0:0002"
      ],
      "sqlite": [
        "mihoyo_wiki:6814:module:11:f607ae7b5a2d:0000",
        "miyoushe:74155917:body:711fe83fbb5c:0000",
        "mihoyo_wiki:7181:tab:0000:3cf96d273aa7:0013",
        "miyoushe:74751748:body:fe8dab3d2db0:0001",
        "mihoyo_wiki:7656:tab:0000:c5d758498a72:0015"
      ]
    },
    {
      "case_id": "identity-video-01",
      "field": "top5_evidence_ids",
      "postgres": [
        "miyoushe:61534034:body:1b8e937a72aa:0000",
        "mihoyo_wiki:2875:tab:0000:7a3fc24c8347:0008",
        "mihoyo_wiki:4998:tab:0000:cbe56a49c938:0001",
        "mihoyo_wiki:2875:tab:0000:049f79c20267:0007",
        "mihoyo_wiki:7495:tab:0000:534e4e81371a:0003"
      ],
      "sqlite": [
        "miyoushe:61534034:body:1b8e937a72aa:0000",
        "mihoyo_wiki:2875:tab:0000:7a3fc24c8347:0008",
        "mihoyo_wiki:2875:tab:0000:049f79c20267:0007",
        "mihoyo_wiki:261:tab:0000:9690886c97cf:0019",
        "mihoyo_wiki:1902:tab:0000:e77c1b69efc2:0006"
      ]
    },
    {
      "case_id": "pending-temporal-01",
      "field": "citation_ids",
      "postgres": [
        "mihoyo_wiki:3253:tab:0000:68d5b20e36fe:0000"
      ],
      "sqlite": [
        "mihoyo_wiki:3975:tab:0000:8f5ce992bee5:0000"
      ]
    },
    {
      "case_id": "relation-himeko-01",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:407:module:20:4be58f894f4a:0000",
        "mihoyo_wiki:1900:tab:0000:4be8f4039640:0000",
        "mihoyo_wiki:7484:module:20:bdbab5490c8c:0000",
        "mihoyo_wiki:5934:tab:0000:35e4c2c10820:0009",
        "mihoyo_wiki:2742:tab:0000:b76b33cb3cdf:0004"
      ],
      "sqlite": [
        "mihoyo_wiki:407:module:20:4be58f894f4a:0000",
        "mihoyo_wiki:7484:module:20:bdbab5490c8c:0000",
        "mihoyo_wiki:411:module:20:6e94764ccbe8:0001",
        "mihoyo_wiki:4442:module:20:24246b842758:0001",
        "mihoyo_wiki:872:module:20:e4aad69a9ee5:0001"
      ]
    },
    {
      "case_id": "relation-himeko-02",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:48:module:19:96c90f0d1447:0001",
        "mihoyo_wiki:3121:module:19:bc4e3216ff02:0001",
        "mihoyo_wiki:7484:module:20:596861a96475:0004",
        "mihoyo_wiki:2085:tab:0000:e66d5b2a28ab:0011",
        "mihoyo_wiki:407:module:20:2844b02362ae:0001"
      ],
      "sqlite": [
        "mihoyo_wiki:48:module:19:96c90f0d1447:0001",
        "mihoyo_wiki:3121:module:19:bc4e3216ff02:0001",
        "mihoyo_wiki:7484:module:20:596861a96475:0004",
        "mihoyo_wiki:407:module:20:fa684933f809:0002",
        "mihoyo_wiki:2085:tab:0000:e66d5b2a28ab:0011"
      ]
    },
    {
      "case_id": "relation-quest-02",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:2690:tab:0000:b0d8a3568c9b:0007",
        "mihoyo_wiki:1085:module:21:a1d3e157bf37:0000",
        "mihoyo_wiki:7181:tab:0000:9884e3ae0c05:0006",
        "mihoyo_wiki:7044:module:11:5187d776b788:0000",
        "mihoyo_wiki:1085:module:20:71440074fed9:0000"
      ],
      "sqlite": [
        "mihoyo_wiki:2690:tab:0000:b0d8a3568c9b:0007",
        "mihoyo_wiki:7181:tab:0000:9884e3ae0c05:0006",
        "mihoyo_wiki:1085:module:21:a1d3e157bf37:0000",
        "mihoyo_wiki:7044:module:11:5187d776b788:0000",
        "mihoyo_wiki:1085:module:20:71440074fed9:0000"
      ]
    },
    {
      "case_id": "relation-quest-03",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:7181:tab:0000:fcc9aeccb4fd:0010",
        "mihoyo_wiki:7484:module:19:7d4ec903ed02:0006",
        "mihoyo_wiki:7384:tab:0000:837d0cde7690:0002",
        "mihoyo_wiki:7120:tab:0000:4a61f565aed3:0030",
        "mihoyo_wiki:7934:tab:0000:2b23bf5f6d49:0024"
      ],
      "sqlite": [
        "mihoyo_wiki:7181:tab:0000:fcc9aeccb4fd:0010",
        "mihoyo_wiki:7484:module:19:7d4ec903ed02:0006",
        "mihoyo_wiki:7384:tab:0000:837d0cde7690:0002",
        "mihoyo_wiki:7934:tab:0000:2b23bf5f6d49:0024",
        "mihoyo_wiki:7120:tab:0000:4a61f565aed3:0030"
      ]
    },
    {
      "case_id": "relation-quest-04",
      "field": "classification",
      "postgres": "passed",
      "sqlite": "ranking_miss"
    },
    {
      "case_id": "relation-quest-04",
      "field": "correct",
      "postgres": true,
      "sqlite": false
    },
    {
      "case_id": "relation-quest-04",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:4972:tab:0000:b2a83b64fbfd:0000",
        "mihoyo_wiki:7120:tab:0000:0116826b5afa:0025",
        "mihoyo_wiki:4596:tab:0000:16a048afff29:0000",
        "mihoyo_wiki:4442:module:11:fbf7a736fb41:0000",
        "mihoyo_wiki:7046:module:11:7e2b6cf2be95:0000"
      ],
      "sqlite": [
        "mihoyo_wiki:4972:tab:0000:b2a83b64fbfd:0000",
        "mihoyo_wiki:3124:module:11:78d3dddc7eb8:0000",
        "mihoyo_wiki:7046:module:11:7e2b6cf2be95:0000",
        "mihoyo_wiki:3128:module:11:731a78624455:0000",
        "mihoyo_wiki:7047:module:11:c108250a3e0d:0000"
      ]
    },
    {
      "case_id": "temp-himeko-01",
      "field": "top5_evidence_ids",
      "postgres": [
        "mihoyo_wiki:7484:module:20:bdbab5490c8c:0000",
        "mihoyo_wiki:6933:tab:0000:6b13573e197e:0000",
        "mihoyo_wiki:7487:tab:0000:9f8e2a6d986f:0000",
        "mihoyo_wiki:7927:tab:0000:2c1ded8cf6d1:0005",
        "mihoyo_wiki:4972:tab:0000:b2a83b64fbfd:0000"
      ],
      "sqlite": [
        "mihoyo_wiki:7484:module:20:bdbab5490c8c:0000",
        "mihoyo_wiki:4972:tab:0000:b2a83b64fbfd:0000",
        "mihoyo_wiki:4970:tab:0000:61c0962f7877:0000",
        "mihoyo_wiki:7120:tab:0000:0116826b5afa:0025",
        "mihoyo_wiki:7476:tab:0000:ee483b7e796e:0033"
      ]
    }
  ],
  "passed": false,
  "postgres_corpus_fingerprint": "df3013318466fab0b4dafa0366de4edd0b818d960e3eb91236893c5f1b644917",
  "postgres_quality_gates": {
    "checks": {
      "direct_answer_at_least_90_percent": false,
      "factual_citations_fully_supported": true,
      "model_generation_disabled": true,
      "top5_at_least_85_percent": false,
      "unanswerable_refusal_accuracy": true,
      "within_two_points_of_sqlite": true
    },
    "passed": false
  },
  "schema_version": 1,
  "score_policy": "numeric score differences are ignored; normalized downstream fields must match",
  "sqlite_corpus_fingerprint": "df3013318466fab0b4dafa0366de4edd0b818d960e3eb91236893c5f1b644917",
  "sqlite_quality_gates": {
    "checks": {
      "direct_answer_at_least_90_percent": false,
      "factual_citations_fully_supported": true,
      "model_generation_disabled": true,
      "top5_at_least_85_percent": false,
      "unanswerable_refusal_accuracy": true,
      "within_two_points_of_sqlite": true
    },
    "passed": false
  },
  "workload": "m9-real-questions-v1"
}
```
