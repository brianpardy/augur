"""Tests for augur mask

NOTE: Several functions are monkeypatched in these tests. If you change the arguments
for any function in mask.py, check that it is correctly updated in this file.
"""
import argparse
import os
import pytest

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from augur import mask

# Test inputs for the commands. Writing these here so tests are self-contained.
@pytest.fixture
def sequences():
    return {
        "SEQ1": SeqRecord(Seq("ATGC-ATGC-ATGC"), id="SEQ1"),
        "SEQ2": SeqRecord(Seq("ATATATATATATATAT"), id="SEQ2")
    }

@pytest.fixture
def fasta_file(tmpdir, sequences):
    fasta_file = str(tmpdir / "test.fasta")
    with open(fasta_file, "w") as fh:
        SeqIO.write(sequences.values(), fh, "fasta")
    return fasta_file

TEST_VCF="""\
##fileformat=VCFv4.2
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO	FORMAT
SEQ	1	.	G	A	.		.
SEQ	2	.	G	A	.		.
SEQ	3	.	C	T	.		.
SEQ	5	.	C	T	.		.
SEQ	8	.	A	C	.		.
"""

@pytest.fixture
def vcf_file(tmpdir):
    vcf_file = str(tmpdir / "test.vcf")
    with open(vcf_file, "w") as fh:
        fh.write(TEST_VCF)
    return vcf_file

TEST_BED_SEQUENCE = [1,2,4,6,7,8,9,10]
# IF YOU UPDATE ONE OF THESE, UPDATE THE OTHER.
TEST_BED="""\
SEQ1	1	2	IG18_Rv0018c-Rv0019c	
SEQ1	4	4	IG18_Rv0018c-Rv0019c	
SEQ1	6	8	IG18_Rv0018c-Rv0019c	
SEQ1	7	10	IG18_Rv0018c-Rv0019c	
"""

@pytest.fixture
def bed_file(tmpdir):
    bed_file = str(tmpdir / "exclude.bed")
    with open(bed_file, "w") as fh:
        fh.write(TEST_BED)
    return bed_file

@pytest.fixture
def mp_context(monkeypatch):
    #Have found explicit monkeypatch context-ing prevents stupid bugs
    with monkeypatch.context() as mp:
        yield mp


@pytest.fixture
def argparser():
    """Provide an easy way to test command line arguments"""
    parser = argparse.ArgumentParser()
    mask.register_arguments(parser)
    def parse(args):
        return parser.parse_args(args.split(" "))
    return parse

class TestMask:
    def test_get_chrom_name_valid(self, vcf_file):
        """get_chrom_name should return the first CHROM field in a vcf file"""
        assert mask.get_chrom_name(vcf_file) == "SEQ"

    def test_get_chrom_name_invalid(self, tmpdir):
        """get_chrom_name should return nothing if no CHROM field is found in the VCF"""
        vcf_file = str(tmpdir / "incomplete.vcf")
        with open(vcf_file, "w") as fh:
            fh.write("##fileformat=VCFv4.2\n")
            fh.write("#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO\n")
        assert mask.get_chrom_name(vcf_file) is None
    
    def test_read_bed_file_with_header(self, bed_file):
        """read_bed_file should ignore header rows if they exist"""
        with open(bed_file, "w") as fh:
            fh.write("CHROM\tSTART\tEND\n")
            fh.write("SEQ\t5\t6")
        assert mask.read_bed_file(bed_file) == [5,6]

    def test_read_bed_file(self, bed_file):
        """read_bed_file should read and deduplicate the list of sites in a bed file"""
        # Not a whole lot of testing to do with bed files. We're basically testing if pandas
        # can read a CSV and numpy can dedupe it.
        assert mask.read_bed_file(bed_file) == TEST_BED_SEQUENCE

    def test_mask_vcf_bails_on_no_chrom(self, tmpdir):
        """mask_vcf should pull a sys.exit() if get_chrom_name returns None"""
        bad_vcf = str(tmpdir / "bad.vcf")
        with open(bad_vcf, "w") as fh:
            fh.write("#")
        with pytest.raises(SystemExit) as err:
            mask.mask_vcf([], bad_vcf, "")
    
    def test_mask_vcf_creates_maskfile(self, vcf_file, mp_context):
        """mask_vcf should create and use a mask file from the given list of sites"""
        mask_file = vcf_file + "_maskTemp"
        def shell_has_maskfile(call, **kwargs):
            assert mask_file in call
        mp_context.setattr(mask, "get_chrom_name", lambda f: "SEQ")
        mp_context.setattr(mask, "run_shell_command", shell_has_maskfile)
        mask.mask_vcf([1,5], vcf_file, vcf_file, cleanup=False)
        assert os.path.isfile(mask_file), "Mask file was not written!"
        with open(mask_file) as fh:
            assert fh.read() == "SEQ	1\nSEQ	5", "Incorrect mask file written!"
    
    def test_mask_vcf_handles_gz(self, vcf_file, mp_context):
        """mask_vcf should recognize when the in or out files are .gz and call out accordingly"""
        def test_shell(call, raise_errors=True):
            assert "--gzvcf" in call
            assert "| gzip -c" in call
        mp_context.setattr(mask, "run_shell_command", test_shell)
        mp_context.setattr(mask, "get_chrom_name", lambda f: "SEQ")
        # Still worth using the fixture here because writing the mask file uses this path
        # Using it for both entries in case god forbid someone starts assuming that path
        # valid earlier than it currently is.
        in_file = vcf_file + ".gz"
        mask.mask_vcf([1,5], in_file, in_file)

    def test_mask_vcf_removes_matching_sites(self, tmpdir, vcf_file):
        """mask_vcf should remove the given sites from the VCF file"""
        out_file = str(tmpdir / "output.vcf")
        mask.mask_vcf([5,6], vcf_file, out_file)
        with open(out_file) as after, open(vcf_file) as before:
            assert len(after.readlines()) == len(before.readlines()) - 1, "Too many lines removed!"
            assert "SEQ\t5" not in after.read(), "Correct sites not removed!"

    def test_mask_vcf_cleanup_flag(self, vcf_file, mp_context):
        """mask_vcf should respect the cleanup flag"""
        tmp_mask_file = vcf_file + "_maskTemp"
        mp_context.setattr(mask, "run_shell_command", lambda *a, **k: None)
        mp_context.setattr(mask, "get_chrom_name", lambda f: "SEQ")

        mask.mask_vcf([], vcf_file, "", cleanup=True)
        assert not os.path.isfile(tmp_mask_file), "Temporary mask not cleaned up"

        mask.mask_vcf([], vcf_file, "", cleanup=False)
        assert os.path.isfile(tmp_mask_file), "Temporary mask cleaned up as expected"
    
    def test_mask_fasta_normal_case(self, tmpdir, fasta_file, sequences):
        """mask_fasta normal case - all sites in sequences"""
        out_file = str(tmpdir / "output.fasta")
        mask_sites = [5,10]
        mask.mask_fasta([5,10], fasta_file, out_file)
        output = SeqIO.parse(out_file, "fasta")
        for seq in output:
            original = sequences[seq.id]
            for idx, site in enumerate(seq):
                if idx not in mask_sites:
                    assert site == original[idx], "Incorrect sites modified!"
                else:
                    assert site == "N", "Not all sites modified correctly!"
    
    def test_mask_fasta_out_of_index(self, tmpdir, fasta_file, sequences):
        """mask_fasta provided a list of indexes past the length of the sequences"""
        out_file = str(tmpdir / "output.fasta")
        max_length = max(len(record.seq) for record in sequences.values())
        mask.mask_fasta([5, max_length, max_length+5], fasta_file, out_file)
        output = SeqIO.parse(out_file, "fasta")
        for seq in output:
            assert seq[5] == "N", "Not all sites masked correctly!"
            original = sequences[seq.id]
            for idx, site in enumerate(seq):
                if idx != 5:
                    assert site == original[idx], "Incorrect sites modified!"
    
    def test_run_recognize_vcf(self, bed_file, vcf_file, argparser, mp_context):
        """Ensure we're handling vcf files correctly"""
        args = argparser("--mask=%s -s %s --no-cleanup" % (bed_file, vcf_file))
        def fail(*args, **kwargs):
            assert False, "Called mask_fasta incorrectly"
        mp_context.setattr(mask, "mask_vcf", lambda *a, **k: None)
        mp_context.setattr(mask, "mask_fasta", fail)
        mp_context.setattr(mask, "copyfile", lambda *args: None)
        mask.run(args)

    def test_run_recognize_fasta(self, bed_file, fasta_file, argparser, mp_context):
        """Ensure we're handling fasta files correctly"""
        args = argparser("--mask=%s -s %s --no-cleanup" % (bed_file, fasta_file))
        def fail(*args, **kwargs):
            assert False, "Called mask_fasta incorrectly"
        mp_context.setattr(mask, "mask_fasta", lambda *a, **k: None)
        mp_context.setattr(mask, "mask_vcf", fail)
        mp_context.setattr(mask, "copyfile", lambda *args: None)
        mask.run(args)

    def test_run_handle_missing_outfile(self, bed_file, fasta_file, argparser, mp_context):
        args = argparser("--mask=%s -s %s" % (bed_file, fasta_file))
        expected_outfile = os.path.join(os.path.dirname(fasta_file), "masked_" + os.path.basename(fasta_file))
        def check_outfile(mask_sites, in_file, out_file):
            assert out_file == expected_outfile
            with open(out_file, "w") as fh:
                fh.write("test_string")
        mp_context.setattr(mask, "mask_fasta", check_outfile)
        mask.run(args)
        with open(fasta_file) as fh:
            assert fh.read() == "test_string"
    
    def test_run_respect_no_cleanup(self, bed_file, tmpdir, vcf_file, argparser, mp_context):
        out_file = os.path.join(os.path.dirname(vcf_file), "masked_" + os.path.basename(vcf_file))
        def make_outfile(mask_sites, in_file, out_file, cleanup=True):
            assert cleanup == False
            open(out_file, "w").close() # need out_file to exist
        mp_context.setattr(mask, "mask_vcf", make_outfile)
        args = argparser("--mask=%s -s %s -o %s --no-cleanup" % (bed_file, vcf_file, out_file))
        mask.run(args)
        assert os.path.exists(out_file), "Output file incorrectly deleted"

    def test_run_normal_case(self, bed_file, vcf_file, tmpdir, argparser, mp_context):
        test_outfile = str(tmpdir / "out")
        def check_args(mask_sites, in_file, out_file, cleanup):
            assert mask_sites == TEST_BED_SEQUENCE, "Wrong mask sites provided"
            assert in_file == vcf_file, "Incorrect input file provided"
            assert out_file == test_outfile, "Incorrect output file provided"
            assert cleanup is True, "Cleanup erroneously passed in as False"
            open(out_file, "w").close() # want to test we don't delete output.
        mp_context.setattr(mask, "mask_vcf", check_args)
        args = argparser("--mask=%s --sequences=%s --output=%s" %(bed_file, vcf_file, test_outfile))
        mask.run(args)
        assert os.path.exists(test_outfile), "Output file incorrectly deleted"
