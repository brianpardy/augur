"""
Annotate a tree with actual and inferred titer measurements.
"""

import json, os, sys
import numpy as np
from collections import defaultdict
from Bio import Phylo

from .reconstruct_sequences import load_alignments
from .utils import read_metadata, read_node_data, write_json


def register_arguments(parser):
    from . import add_default_command

    subparsers = parser.add_subparsers()
    add_default_command(parser)

    tree_model = subparsers.add_parser('tree', help='tree model')
    tree_model.add_argument('--titers', type=str, required=True, help="file with titer measurements")
    tree_model.add_argument('--tree', '-t', type=str, required=True, help="tree to perform fit titer model to")
    tree_model.add_argument('--output', '-o', type=str, required=True, help='JSON file to save titer model')
    tree_model.set_defaults(
        __command__ = infer_tree_model
    )

    sub_model = subparsers.add_parser('sub', help='substitution model')
    sub_model.add_argument('--titers', type=str, required=True, help="file with titer measurements")
    sub_model.add_argument('--alignment', nargs='+', type=str, required=True, help="sequence to be used in the substitution model, supplied as fasta files")
    sub_model.add_argument('--gene-names', nargs='+', type=str, required=True, help="names of the sequences in the alignment, same order assumed")
    sub_model.add_argument('--tree', '-t', type=str, help="optional tree to annotate fit titer model to")
    sub_model.add_argument('--output', '-o', type=str, required=True, help='JSON file to save titer model')
    sub_model.set_defaults(
        __command__ = infer_substitution_model
    )


class infer_substitution_model():
    def run(args):
        from .titer_model import SubstitutionModel
        alignments = load_alignments(args.alignment, args.gene_names)

        TM_subs = SubstitutionModel(alignments, args.titers)
        TM_subs.prepare()
        TM_subs.train()

        subs_model = {'titers':TM_subs.compile_titers(),
                      'potency':TM_subs.compile_potencies(),
                      'avidity':TM_subs.compile_virus_effects(),
                      'substitution':TM_subs.compile_substitution_effects()}

        # Annotate nodes with inferred titer drops, if a tree is given.
        if args.tree:
            tree = Phylo.read(args.tree, 'newick')
            tree.root.cTiterSub = 0
            nodes = {
                tree.root.name: {
                    "dTiterSub": 0,
                    "cTiterSub": 0
                }
            }

            for node in tree.find_clades():
                for child in node.clades:
                    # Get mutations between the current node and its parent.
                    mutations = TM_subs.get_mutations(child.name, node.name)

                    # Calculate titer drop on the branch to the current node.
                    dTiterSub = 0
                    for gene, mutation in mutations:
                        dTiterSub += TM_subs.substitution_effect.get((gene, mutation), 0)

                    # Calculate the cumulative titer drop from the root to the current node.
                    child.cTiterSub = node.cTiterSub + dTiterSub

                    # Store annotations for export to JSON.
                    nodes[child.name] = {
                        "dTiterSub": dTiterSub,
                        "cTiterSub": child.cTiterSub
                    }

            subs_model["nodes"] = nodes

        # export the substitution model
        write_json(subs_model, args.output)

        print("\nInferred titer model of type 'SubstitutionModel' using augur:"
              "\n\tNeher et al. Prediction, dynamics, and visualization of antigenic phenotypes of seasonal influenza viruses."
              "\n\tPNAS, vol 113, 10.1073/pnas.1525578113\n")
        print("results written to", args.output)


class infer_tree_model():
    def run(args):
        from .titer_model import TreeModel
        T = Phylo.read(args.tree, 'newick')
        TM_tree = TreeModel(T, args.titers)
        TM_tree.prepare()
        TM_tree.train()

        # export the tree model
        tree_model = {'titers':TM_tree.compile_titers(),
                      'potency':TM_tree.compile_potencies(),
                      'avidity':TM_tree.compile_virus_effects(),
                      'nodes':{n.name:{"dTiter": n.dTiter, "cTiter":n.cTiter}
                                  for n in T.find_clades()}}
        write_json(tree_model, args.output)
        print("\nInferred titer model of type 'TreeModel' using augur:"
              "\n\tNeher et al. Prediction, dynamics, and visualization of antigenic phenotypes of seasonal influenza viruses."
              "\n\tPNAS, vol 113, 10.1073/pnas.1525578113\n")
        print("results written to", args.output)
