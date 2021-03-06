#!/usr/bin/python
from helpers import *

####################
# global variables #
####################

n = 10  # n: Number of computers in the network 
k = 4   # k: Number of computers that need to agree 

# g is an agreed upon element in Z*_n that has high order
# e = the public key

# B1 is the bound used in 5.2.1 distributed sieving method
B1 = 1 << 15
# B2 is the bound used in 5.2.3
B2 = 1 << 19 #we need this to be lower than our list of primes

# N = public modulus
# for now lets just make the the product of 2 large random primes
bits_secure = 1024

class Network:
    def __init__(self, sayingYes = []):
        print "network init"
        self.nodes = []
        for i in range(n):
            if i in sayingYes:
                self.nodes.append(Computer(self, i, True))
            else:
                self.nodes.append(Computer(self, i, False))

    def get_nodes(self):
        return self.nodes

    '''
    setup: 
        
    Creates the global variables used in the network. Creates the following
    variables:
    0.  p, q - two large unknown primes*
    1.  p_i for i = 1..n, where computer i knows p_i and the sum of all p_i = p
    2.  q_i for i = 1..n, where computer i knows q_i and the sum of all q_i = q
    3.  N - the public RSA modulus that is the product of two pq, known to everyone
    4.  M - a large public prime 
    5.  e - the public encryption key
    6.  d - the corresponding decryption key, unknown to everyone
    7.  d_i for i = 1..n, where computer i knows d_i and the sum of all d_i = d
    8.  g - a generator of of Z*_N
    This function needs to be run only once.

    *We offer noniteractive generation of p,q which has the benefits of making the code
    significantly faster, but would mean the network creates p,q

    Discussion of the iteractive process is done in the paper. 
    '''
    def setup(self):
        print "Starting Network Setup"
        
        # Generate N, generates p_i, q_i
        self.generate_N(iteractive = False)

        # verify that N is indeed a product of two primes
        while not self.verify_N():
            self.generate_N()
            
        # choose the public encryption key e and generator g
        self.choose_e_and_g()

        # generates the d_i
        self.private_key_generation()

        # interactive protocol that generates information required for signature scheme
        deal = self.dealing_algorithm()
        if not deal:
            raise RuntimeError("user found an issue in the deals")

        print "Finished Network Setup" 

    '''
    generate_N:

    Generates the value of N, and verifies that it is the product of two primes.
    At the end of this function, every computer will know N, as well as the shares p_i and q_i,
    such that they sum to p, q respectively where N=pq. 

    paramters:
        iteractive - boolean, if True N will be generated interactively by the computers
                            , if False N will be generated manually by the network
        debug - boolean, if True prints debugging messages
    '''
    def generate_N(self, iteractive = True, debug=False):        
        if  not iteractive:
            M = get_random_prime(1 << 2050, 1 << 2051)
            for computer in self.nodes:
                computer.M = M
                assert gmpy2.is_prime(computer.M) == True


            p = get_random_prime(2**1024,2**1025)
            q = get_random_prime(2**1024,2**1025)
            N = p*q

            shares_p_i = getShares(p,n,M)
            shares_q_i = getShares(q,n,M)
            for i in range(len(self.nodes)):
                self.nodes[i].p_i = shares_p_i[i]
                self.nodes[i].q_i = shares_q_i[i]
                self.nodes[i].N = N
            return
        else:

            # This M is the product of all primes in the range (n, B1]
            # This M is a temporary value
            M = reduce(multiply, get_primes_in_range(n + 1, B1))

            for computer in self.nodes:
                computer.M = M

            self.generate_pq(M, debug)

            # for hanna_generate_pq_test
            if debug:
                return

            # At this point the last value that we put as p_i should be n_j
            for computer in self.nodes:
                computer.p_i = computer.bgw.n_j

            # Then generate q_i using the same method.
            self.generate_pq(M, debug)
            for computer in self.nodes:
                computer.q_i = computer.bgw.n_j

            # Now, M is a large prime, larger than N
            M = get_random_prime(1 << 2050, 1 << 2051)
            for computer in self.nodes:
                computer.M = M
                assert gmpy2.is_prime(computer.M) == True

            # Compute N using BGW since now every computer has its own p_i and q_i
            for computer in self.nodes:
                computer.one_round_BGW_phase_0(M, computer.p_i, computer.q_i, computer.pq.l)
            for computer in self.nodes:
                computer.one_round_BGW_phase_1()
            for computer in self.nodes:
                computer.one_round_BGW_phase_2()

            # At this point, every computer has its share of N as computer.bgw.n_j,
            # so we just sum up every computer's n_j to get N
            # Alternatively, each computer can broadcast each n_j to everyone
            N = mod(sum(map(lambda comp: comp.bgw.n_j, self.nodes)), M)
            for computer in self.nodes:
                computer.N = N

    '''
    verify_N:
    
    Verifies that the RSA modulus, N is a product of two primes.
    '''
    def verify_N(self):
        if self.parallel_trial_division():
            return self.load_balance_primality_test()
        return False

    '''
    parallel_trial_division:

    Each computer tries and checks if N is divisible by any small number

    returns:   
        Boolean if N passes the checks
    '''
    def parallel_trial_division(self):
        for computer in self.nodes:
            if not computer.trial_division():
                print "bad N fails trial division"
                return False
        return True

    '''
    load_balance_primality_test:

    checks if N is the product of two primes

    returns:   
        Boolean if N is the product of two primes
    '''
    def load_balance_primality_test(self):
        N = self.nodes[0].N
        for computer in self.nodes:
            if N!= computer.N:
                raise RuntimeError("Not all computers had the same N")

        g = get_relatively_prime_int(N)
        for computer in self.nodes:
            computer.load_balance_primality_test_phase_1(g)
        for computer in self.nodes:
            if not computer.load_balance_primality_test_phase_2(g):
                print "N is not the product of two primes"
                return False
        return True


    '''
    generate_pq:

    parameters:
        M - a large prime

    Runs the protocol to give each computer their share of p_i or q_i.
    The same protocol is used for both p_i and q_i so we run this twice.
    At the end of this function, self.pq.u[-1] should be the value of the share.
    '''
    def generate_pq(self, M, debug=False):
        for computer in self.nodes:
            computer.generate_pq_setup(M)

        # gcd(a, M) should be 1
        a = mod(reduce(multiply, [comp.pq.a_i for comp in self.nodes]), M)

        if GCD(a, M) != 1:
            raise RuntimeError("gcd(a, M) is not 1 in generate_pq")

        # round is initialized as 0 for every computer, and updated for every computer at the same time
        while self.nodes[0].pq.round < n:
            r = self.nodes[0].pq.round
            for computer in self.nodes:
                if len(computer.pq.u) != r+1 or len(computer.pq.v) != r+1:
                    raise RuntimeError("Wrong length for u or v, computer ", computer.id)
            for computer in self.nodes:
                computer.one_round_BGW_phase_0(M, computer.pq.u[r], computer.pq.v[r], computer.pq.l)
            for computer in self.nodes:
                computer.one_round_BGW_phase_1()
            for computer in self.nodes:
                computer.one_round_BGW_phase_2()
            
            if deug:
                product = mod(reduce(multiply, [self.nodes[i].pq.a_i for i in xrange(r+1)]), M)
                current_sum = mod(reduce(add, [comp.bgw.n_j for comp in self.nodes]), M)
                if product != current_sum:
                    raise RuntimeError("product of a_i so far not equal to sum of the latest bgw shares")

            for computer in self.nodes:
                computer.generate_pq_update()
        if debug:
            p = mod(reduce(add, [comp.bgw.n_j for comp in self.nodes]), M)
            print "p == a", p == a

    '''
    choose_e_and_g:

    Chooses the public exponent and the generator randomly and gives them to the computers
    '''
    def choose_e_and_g(self):
        e = 65537 # magic number, due issues involving not invertible values
        g = get_random_int(self.nodes[0].N)

        for computer in self.nodes:
            computer.e = e
            computer.g = g


    """
    dealing_algorithm:

    each user with their share of the private key d_i
    the users agree on a k and global public S
    Each player gets Public Private share pair (P_i,S_i)
    which is needed to implement the signature scheme
    takes paramters
    prime M > N
    threshold k
    element g of high order Z_N
    S the set of all users
    """
    def dealing_algorithm(self):
        for user in self.nodes:
            #calculation phase
            user.dealing_phase_1()
        for user in self.nodes:
            #print "user id = ",user.id+1
            #verfication phase
            if not user.dealing_phase_2():
                print "aborted, user",user.id+1,", found an error"
                return False
        return True

    '''
    sign:

    Produce a valid signature for the given message if at least k computers agree.

    parameters:
        message - the message encoded as an integer to be signed 

    '''
    def sign(self, message):

        # If fewer than k computers say yes, then abort
        agreed_computers = [computer for computer in self.nodes if computer.agree]
        if len(agreed_computers) < k:
            print "Only %d computers agreed, need %d, aborting signature." %(len(agreed_computers),k)
            return

        # Pick any k (we pick the first k) of the agreeing computers, and let them be the set of interest.
        # We use a tuple because a tuple can be used as a dictionary key.
        I = tuple(agreed_computers[:k])
        I_prime = [computer for computer in self.nodes if computer not in I]

        # Prepare the k computers to run the algorithm.
        for computer in I:
            computer.setup(I, I_prime)

        # If this set of computers has not previously run the subset presigning algorithm before, then run it
        # This algorithm produces public information to produce signature shares
        if I not in I[0].subsets:
            self.subset_presigning_algorithm(I)
        else:
            print "This subset has already run the presigning algorithm."

        # Have each computer generate a signature share and proof (6.2.3 and 6.2.4 in the paper)
        for computer in I:
            computer.signature_share_generation(message)
        for computer in I:
            computer.signature_share_verification()

        # Each computer combines the shares (6.2.5 in the paper)
        for computer in I:
            computer.combine_signatures(message)

        # Print out the final signature
        for computer in I:
            print "Signature: " + str(computer.id) + " " + str(computer.signature)

    '''
    subset_presigning_algorithm:

    Implements the subset presigning algorithm in multiple phases.
    
    parameters:
        I - the set of k agreeing computers. We define I_prime to be the remaining set of n-k computers.
    '''
    def subset_presigning_algorithm(self, I):

        # Every computer performs each phase together
        for t_i in I:
            t_i.subset_presigning_algorithm_phase_0()
        for t_i in I:
            t_i.subset_presigning_algorithm_phase_1()
        for t_i in I:
            t_i.subset_presigning_algorithm_phase_2()
        for t_i in I:
            t_i.subset_presigning_algorithm_phase_3()

        ### Checks ###    
        # X_I should be given, check that sum s in I = sum d in I'+x_I*M    
        ssum = 0
        dsum = 0
        xi = 0
        M = 0
        for comp in I:
            ssum = add(ssum,comp.presigning_data[comp.I].s_t_i)
            xi = comp.presigning_data[comp.I].x_I
            M = comp.M
        for comp in [computer for computer in self.nodes if computer not in I]:
            dsum = add(dsum,comp.d_i)
        assert ssum == dsum + xi*M
        ### End Checks ###
            
        for t_i in I:
            t_i.subset_presigning_algorithm_phase_4()

    '''
    private_key_generation:

    Generates the private keys d_i

    '''
    def private_key_generation(self,):

        # Goes through the process as described in 5.2.5
        for user in self.nodes:
            user.create_phi_i()
            user.distribute_phi_i_j()
        for user in self.nodes:
            user.distribute_sum_phi_j()
        for user in self.nodes:
            user.generate_phi_and_psi()

        ### Checks ###
        phisum = 0
        for user in self.nodes:
            phisum = add(phisum,user.phi_i)
        for user in self.nodes:
            assert 0 == mod(subtract(user.psi,phisum),user.e)
        ### End Checks

        for user in self.nodes:
            user.generate_d_i()

        # trial decryption 5.2.6
        message = 1234567
        for user in self.nodes:
            user.generate_message_i(message)

        # user 1 updates his share based on the messages
        self.nodes[0].process_messages(message)

class Computer:
    def __init__(self, network, _id, agree):
        self.network = network
        self.id = _id
        self.agree = agree

        # Variables for RSA secret keys and modulus
        self.N = None   # the shared public modulus for RSA
        self.M = None   # some number larger than N
        self.g = None   # the generator, something that has high order in Z*_n
        self.e = None   # the RSA public key
        self.p_i = None # this computer's share of prime p
        self.q_i = None # this computer's share of prime q
        self.d_i = None # this computer's share of the secret key d

        # Intermediate variables needed to generate RSA modulus and secret key shares
        self.bgw = None # data for running BGW protocol; the data is replaced every time we run the protocol
        self.pq = None # data to store intermediate values

        # to check if N is the product of two primes
        self.v = [0]*n

        # for primality testing, each node has a list of prime
        primes = get_primes_in_range(B1,B2)

        self.primes = [primes[i] for i in xrange(len(primes)) if i%n==self.id]

        # Variables for the dealing algorithm
        self.f_i_j = [1] * n # array that stores f_i_j for each i in range 0...n-1 (j is self)
        self.a_i_j = []

        # the array for the commitments of of the coefficients of the polynomial
        # we get them from all other users, thus the n by n array
        self.b_i_j = [[0]*n for i in xrange(n)]
        
        # Intermediate variables needed to calculate the private share d_i
        self.phi_i = None
        self.phi_i_j = [0]*n        # gets one phi_i_j from each computer
        self.sum_phi_i_j = [0]*n    # sum of all phi_i_j of computer j, every computer will eventually have the same list
        self.psi = None             # phi(n) mod e
        self.psi_inv = None         # psi inv mod e
        self.message_i = [0]*n      # for trial decryption 5.2.6
        
        # Variables set at the end of the dealing algorithm
        self.S = {}     # {k,M,g}
        self.P_i = []   # {{b_j,l}_j=1,...,n,l=0,...,k-1}
        self.S_i = {}   # {d_i,{a_i,j}_j=1,...,k-1,{f_j,i}_i!=j}

        # Variables for the subset presigning algorithm
        self.dummy_message = None
        self.I = None               # the current subset
        self.I_prime = None         # the complement of the current subset
        self.subsets = []           # this is a history of all subsets that this computer has been part of
        self.presigning_data = {}   # maps subset -> this computer's presigning data for that subset

        # Variables for share generation/verification/combining
        self.sigmas = [] # contains tuples of the form (c_i, [m, (-,-), c_i, r, c, id])
                         # there should be k items in self.sigmas

        self.signature = None # the final signature produced after combining k shares


    '''
    change_choice:

    Change this computer's vote to be yes or no (set agree to True or False)

    parameters:
        agree - a boolean 
    '''
    def change_choice(self, agree):
        self.agree = agree


    #####################################################
    # Functions for Deciding N, e, d_i, g
    #####################################################
    '''
    generate_pq_setup:

    Protocol among the computers for generating the shares of p and q.
    All arithmetic should be done modulo M.

    This function sets up the data structure needed for calculating p_i and q_i,
    and generates a random a_i that is relatively prime to M.

    parameters:
        M - a large prime
    '''
    def generate_pq_setup(self, M):
        # Initialize PQData with round = 0, M = M, l = floor((n-1)/2)
        self.pq = PQData(0, M, int(math.floor((n-1)/2)))
        
        # Let a_i be some random integer relatively prime to M
        self.pq.a_i = get_relatively_prime_int_small(M)
        if GCD(self.pq.a_i, M) != 1:
            raise RuntimeError("The impossible has happened.")
        
        # Set the first (zeroeth) value in u and v.
        # Since this is the first round, the first (zeroeth) computer sets u[round] = a_i
        # but all the other computers set everything to 0
        if self.id == self.pq.round:
            self.pq.u.append(self.pq.a_i)
            self.pq.v.append(1)
        else:
            self.pq.u.append(0)
            self.pq.v.append(0)


    '''
    receive_fgh:

    Receives a (f, g, h) tuple from a computer, and adds it
    to the array self.bgw.received_fgh.

    parameters:
        fgh_tuple - a tuple message from another computer
    '''
    def receive_fgh(self, fgh_tuple):
        self.bgw.received_fgh.append(fgh_tuple)
        # print "fgh: ", fgh_tuple

    '''
    one_round_BGW_phase_0:

    Begins to run one round of the BGW protocol (section 4.3).

    When this function is called, self.pq.round is the round where the latest
    u and v values were placed. For example, the first time one_round_BGW is called,
    we expect round = 0 because we just started the algorithm.

    Phase 0 simply sets the self.bgw data structure with the correct values.

    parameters:
        M - a large prime
        p_i - private additive share of p
        q_i - private additive share of q
        l - floor(n-1/2)
    '''
    def one_round_BGW_phase_0(self, M, p_i, q_i, l):
        # Reset to a new BGWData instance with data from the latest round.
        # self.bgw = BGWData(self.pq.M, self.pq.u[self.pq.round], self.pq.v[self.pq.round], self.pq.l)
        self.bgw = BGWData(M, p_i, q_i, l)

    '''
    one_round_BGW_phase_1:

    Phase 1 generates random coefficients for the polynomials,
    and calculates and broadcasts the f_i(j) values to each computer j.
    '''
    def one_round_BGW_phase_1(self):
        # Generate the random coefficients in arrays a, b, and c
        # Note that a and b have length l, while c has length 2l
        # for count in xrange(self.bgw.l):
        #     self.bgw.a.append(get_random_int(self.bgw.M))
        #     self.bgw.b.append(get_random_int(self.bgw.M))
        #     self.bgw.c.append(get_random_int(self.bgw.M))

        # for count_again in xrange(self.bgw.l):
        #     self.bgw.c.append(get_random_int(self.bgw.M))

        self.bgw.a = [1 for i in xrange(self.bgw.l)]
        self.bgw.b = [1 for i in xrange(self.bgw.l)]
        self.bgw.c = [1 for i in xrange(2*self.bgw.l)]


        # Calculate and broadcast fgh tuples as descrribed in section 4.3 steps 1 and 2
        for computer in self.network.nodes:
            x = computer.id + 1  # the x value to evaluate the polynomial at
            x_j = map(lambda ex: powmod(x, ex + 1, self.bgw.M), range(2*self.bgw.l)) # calculate the relevant powers of x
            f = mod(self.bgw.p_i + reduce(add,map(lambda idx: mulmod(self.bgw.a[idx], x_j[idx], self.bgw.M), range(self.bgw.l))), self.bgw.M)
            g = mod(self.bgw.q_i + reduce(add,map(lambda idx: mulmod(self.bgw.b[idx], x_j[idx], self.bgw.M), range(self.bgw.l))), self.bgw.M)
            h = mod(reduce(add,map(lambda idx: mulmod(self.bgw.c[idx], x_j[idx], self.bgw.M), range(2*self.bgw.l))), self.bgw.M)
            computer.receive_fgh((f, g, h))

    '''
    one_round_BGW_phase_2: 

    In phase 2, after receiving (f, g, h) tuples, the computer finishes the BGW protocol
    by calculating N_j and then converting it to n_j, the additive share,
    and saving the additive share in self.pq.n_j
    '''
    def one_round_BGW_phase_2(self):
        # Calculate N_j as described in section 4.3 step 3
        sum_f = sum_g = sum_h = 0
        for f, g, h in self.bgw.received_fgh:
            sum_f = mod(add(sum_f, f), self.bgw.M)
            sum_g = mod(add(sum_g, g), self.bgw.M)
            sum_h = mod(add(sum_h, h), self.bgw.M)

        N_j = mod(add(multiply(sum_f, sum_g), sum_h), self.bgw.M)
        
        # Calculate n_j as described in section 4.3.2
        n_j = N_j
        bottom = 1
        for h in xrange(n):
            if h != self.id:
                n_j = multiply(multiply(n_j,h + 1),powmod(h-self.id,-1, self.bgw.M))

        self.bgw.n_j = mod(n_j, self.bgw.M)

    '''
    generate_pq_update:

    Update u and v arrays in between rounds of BGW.
    '''
    def generate_pq_update(self):
        # Set the next value in self.pq.u as the share calculated in the last round of BGW
        self.pq.u.append(self.bgw.n_j)
        
        # Update the round.
        self.pq.round += 1
        
        # Set the next value in self.pq.v depending on if it's our turn or not.
        if self.id == self.pq.round:
            self.pq.v.append(self.pq.a_i)
        else:
            self.pq.v.append(0)


    '''
    trial_division:

    Check for small factors of N

    return:
        if N is not divisble by small factors
    '''
    def trial_division(self,debug = False):
        N = self.N
        for prime in self.primes:
            if N%prime==0:
                if debug:
                    print "N=prime*x"
                    print "N",N
                    print "prime",prime
                    print "x",N/prime
                return False
        return True

    '''
    load_balance_primality_test_phase_1:

    Check if N is prime
    Broadcast phase

    parameters:
        g - generator of Z*_n
    '''
    def load_balance_primality_test_phase_1(self,g):
        N = self.N
        if self.id == 0:
            v = powmod(g,N-self.p_i-self.q_i+1,N)
        else:
            v = powmod(g,self.p_i+self.q_i,N)

        for computer in self.network.nodes:
            computer.v[self.id]=v

    '''
    load_balance_primality_test_phase_2:

    Check if N is prime
    Broadcast phase

    parameters:
        g - generator of Z*_n
    '''
    def load_balance_primality_test_phase_2(self,g):
        N = self.N
        v1 = self.v[0]
        rest = 1

        for i in range(1,n):
            rest = mulmod(rest,self.v[i],N)

        return v1 == rest


    #####################################################
    # Stuff for the Dealing Algorithm (6.2.1)
    #####################################################

    # dealing algorithm (6.2.1)
    # computers i=1...n agree on the following parameters
    # # # prime M > N
    # # # threshold k where 1 < k < n
    # # # element g of high order Z_N*
    # each computer picks random degree (k-1) polynomial f_i in Z_m
    # # # f_i(x) = a_{i,k-1}x^{k-1}+...+a_{i,1}x+d_i
    # ith computer computes f_i(j) and send to computer P_j for all j=1..n
    # note this is the Shamir sharing of d_i
    # ith computer also computes b_{i,j}=g^{a_{i,j}} mod N for j = 0...(k-1)
    # # # broadcasts these values
    # # # these are the commitments
    # at this point each computer j has recieved f_{1,j},...,f_{n,j} and verifies
    # # # g^{f_{i,j}} = g^{f_i(j)} mod N = g^{a_{1,k-1}j^{k-1}+...+a_{i,1}j+d_i}
    # # #             =
    def dealing_phase_1(self):
        M = self.M
        assert gmpy2.is_prime(M) == True
        g = self.g
        S = self.network.nodes

        selfid = self.id+1
        
        # pick the random polynomial
        self.a_i_j = [0]*k
        self.a_i_j[0] = self.d_i
        for i in xrange(1,k):
            self.a_i_j[i] = get_random_int(M)

        # calculate f_i_j for each other user and set their values
        # f_i_j = f_i(j)
        for user in S: # for user in set
            #if user != self: # those that are not you
            userid = user.id+1
            f_i_j = 0
            for c in xrange(k-1,-1,-1):
                f_i_j+=multiply(self.a_i_j[c],powmod(userid,c,M))

            user.f_i_j[self.id]=f_i_j
        for user in S:
            for j in xrange(0,k):
                user.b_i_j[self.id][j]=powmod(g,self.a_i_j[j],self.N)


    def dealing_phase_2(self):
        M = self.M
        g = self.g
        S = self.network.nodes
        selfid = self.id+1

        # check to ensure people sent out the correct values
        for user_i in S:
            #if user_i != self:
            user_iid = user_i.id+1
            g_exp_f_i_j = powmod(g,self.f_i_j[user_i.id], self.N)
            checker = gmpy2.mpz(1)
            for t in xrange(k):
                checker=multiply(checker,powmod(self.b_i_j[user_i.id][t],powmod(selfid,t,self.N),self.N))
            checker = mod(checker,self.N)
            if checker != g_exp_f_i_j:
                return False

        # set the final values
        self.S["k"] = k
        self.S["M"] = M
        self.S["g"] = g
        self.P_i = self.b_i_j 
        self.S_i["d_i"]=self.d_i
        self.S_i["a_i,j"]=self.a_i_j[1:] # we don't want the term a_0
        self.S_i["f_j,i"]=self.f_i_j # there is a 0 where self is for indexing purposes
        return True



    #####################################################
    # Stuff for the Subset Presigning Algorithm (6.2.2)
    #####################################################
    '''
    setup:

    Sets up this computer as a member of the set I,
    and clears previous signatures and sigmas from the last round of signing.

    parameters: 
        I - set of agreeing parties
        I_prime - set of nonagreeing parties
    '''
    def setup(self, I, I_prime):
        self.I = I
        self.I_prime = I_prime

        self.sigmas = [] # reset this to empty
        self.signature = None
        print "Hi I am computer %d." % self.id # Remove after debugging

    '''
    Receive a broadcast of a different computer's h_t_i
    and the computer's id, as a tuple.
    '''
    def receive_presigning_h_t_i(self, id_and_h_t_i):
        self.presigning_data[self.I].received_h_t_i[id_and_h_t_i[0]] = id_and_h_t_i[1]

    '''
    Receive a broadcast of a different computer's calculated x_I
    and the computer's id, as a tuple.
    '''
    def receive_presigning_x_I(self, id_and_x_I):
        self.presigning_data[self.I].received_x_I.append(id_and_x_I)


    '''
    Returns a copy of the current subset presigning data.
    '''
    def get_current_subset_presigning_data(self):
        return (copy.deepcopy(self.presigning_data[self.I].S_I_t_i),
            copy.deepcopy(self.presigning_data[self.I].D_I))

    '''
    Runs the subset presigning algorithm, where <computers>
    is an array of the k computers (including this one)
    that agree to sign the message.

    Note that this only needs to be run ONCE for each unique
    subset of k computers that wish to sign a message.

    Phase 0 involves adding I to the array of subsets
    and creating an instance of PresigningData for this set I
    '''
    def subset_presigning_algorithm_phase_0(self):
        # Sanity check to make sure we haven't already run the algorithm for this subset.
        if self.I in self.subsets:
            raise RuntimeError("Should not run subset presigning algorithm (phase 0) on a previously seen subset.")

        # Add this set I to the self.subsets array and create a new PresigningData instance
        self.subsets.append(self.I)
        self.presigning_data[self.I] = PresigningData()
        self.dummy_message = powmod(2, self.e, self.N)

    '''
    Phase 1 involves calculating lambda_t_i, s_t_i, and h_t_i,
    and broadcasting h_t_i.
    '''
    def subset_presigning_algorithm_phase_1(self):
        # Compute lambda_t_i
        lambda_t_i = 1
        bottoms = 1

        for computer in self.I:
            if computer.id == self.id:
                continue
            lambda_t_i = multiply(multiply(lambda_t_i, computer.id + 1),powmod(computer.id - self.id,-1,self.M))
        lambda_t_i = mod(lambda_t_i, self.M)
        self.presigning_data[self.I].lambda_t_i = lambda_t_i

        # Compute s_t_i = (sum(f_i_j) * lambda_t_i) % M
        I_prime_ids = map(lambda computer: computer.id, self.I_prime)
        s_t_i = mod(multiply(reduce(add, [self.f_i_j[i] for i in I_prime_ids]), lambda_t_i), self.M)
        self.presigning_data[self.I].s_t_i = s_t_i
        self.presigning_data[self.I].S_I_t_i = s_t_i

        # Compute h_t_i
        h_t_i = powmod(self.g, s_t_i, self.N)
        self.presigning_data[self.I].h_t_i = h_t_i

        # Broadcast h_t_i so other computers can use it to verify later,
        # and also broadcast to yourself just so your array is complete with all k elements.
        for computer in self.I:
            computer.receive_presigning_h_t_i((self.id, h_t_i))

    '''
    Phase 2 involves computing the signature share on a dummy message,
    and broadcasting the signature share to every other computer in I.
    '''
    def subset_presigning_algorithm_phase_2(self):
        # Compute and broadcast the signature share.
        
        ### Check ###
        ssum = 0
        for computer in self.I:
            ssum = add(ssum, computer.presigning_data[self.I].S_I_t_i)

        dsum = 0
        for computer in self.I_prime:
            dsum = add(dsum, computer.d_i)
        dsum = mod(dsum,self.M)

        assert mod(subtract(ssum, dsum),self.M) == 0
        ### End Check ###

        signature_share = self.signature_share_generation(self.dummy_message)

    '''
    Phase 3 involves verifying the signature shares that have been broadcasted,
    finding x_I via exhaustive search, and then broadcasting x_I.
    '''
    def subset_presigning_algorithm_phase_3(self):
        # Check that we received a signature share from all k-1 other computers in the group.
        if len(self.sigmas) != k:
            "Didn't receive signature share on dummy message from k-1 other computers."
            raise RuntimeError("Didn't receive signature share on dummy message from k-1 other computers.")

        # Verify each signature share.
        if not self.signature_share_verification():
            raise RuntimeError("Invalid signature on dummy message in subset presigning.")

        # If everything checks out, then continue on with the algorithm.

        # Find x_I by checking all possible values
        possible_x_I = range(k-n, k+1) # x_I can be between k-n and k inclusive.

        # Calculate the product of the received signature shares.
        product_c_prime_t_i = mod(reduce(multiply,
            map(lambda sigma: sigma[0],
                self.sigmas)), self.N)
        
        two_e_M = powmod(2, multiply(self.e, self.M), self.N)
        
        # Search for the value of x_I that makes the product = 2 * (2^(e*M*x_I))
        x_I = None
        for x in possible_x_I:
            if product_c_prime_t_i == mod(multiply(2, powmod(two_e_M, x, self.N)), self.N) :
                x_I = x
                break
        
        if x_I is None:
            raise RuntimeError("Couldn't find viable x_I in subset presigning algorithm, computer " + str(self.id))
        self.presigning_data[self.I].x_I = x_I

        # Broadcast x_I so everyone can verify that they found the same x_I
        for computer in self.I:
            if computer.id != self.id:
                computer.receive_presigning_x_I((self.id, x_I))

    '''
    Phase 4 involves verifying the x_I that have been broadcasted,
    and then setting D_I and S_I_t_i for this subset.
    '''
    def subset_presigning_algorithm_phase_4(self):
        # Verify all received x_I (check that they are the same as what we found).
        if len(self.presigning_data[self.I].received_x_I) != k-1:
            raise RuntimeError("Didn't receive enough x_I values in subset presigning.")
        
        for _id, x in self.presigning_data[self.I].received_x_I:
            if x != self.presigning_data[self.I].x_I:
                print "Computer %d broadcasted x_I value %d, but this computer (%d) has x_I value %d" %(_id, x, self.id, self.presigning_data[self.I].x_I)
                raise RuntimeError("Didn't match x_I.")

        # Set D_I and S_I_t_i
        self.presigning_data[self.I].S_I_t_i = self.presigning_data[self.I].s_t_i # seems stupid but they do it in the paper
        
        # Aggregate the received sigmas and h_t_i into an array
        h_sigma_array = []
        
        # Make sure we have k sigmas and k h_t_i values.
        if len(self.sigmas) != k or len(self.presigning_data[self.I].received_h_t_i) != k:
            raise RuntimeError("Didn't receive k sigmas or h_t_i values.")
        
        # Match them up and aggregate into h_sigma_array
        for sigma, proof in self.sigmas:
            id_s = proof[-1] # the id is the last thing in the proof array
            for id_h, h_t_i in self.presigning_data[self.I].received_h_t_i.items():
                if id_s == id_h:
                    h_sigma_array.append((id_s, h_t_i, sigma))
                    break
        
        # Make sure that we got k tuples after matching, otherwise there are unmatched values.
        if len(h_sigma_array) != k:
            raise RuntimeError("Couldn't match h_t_i and sigma values appropriately.")

        self.presigning_data[self.I].D_I = (self.presigning_data[self.I].x_I, h_sigma_array)

        # clear self.sigmas
        self.sigmas = []

    ###############################################################
    # Stuff for the Signature Share Generation and Verification
    ###############################################################

    '''
    Receives a sigma from another computer
    and saves it in self.sigmas
    '''
    def receive_sigma(self, sigma):
        self.sigmas.append(sigma)

    '''
    Given a message and the relevant set of k computers,
    computes and broadcasts a tuple containing a signature and a proof.

    Also saves the signature share (both the signature and the proof) in self.sigmas.
    Also returns the signature share.
    '''
    def signature_share_generation(self, m):
        #needs to be fixed for unknown order of g mod N
        d_i = self.d_i
        s_i = self.presigning_data[self.I].S_I_t_i
        b_ti0 = self.b_i_j[self.id][0]
        h_ti = self.presigning_data[self.I].h_t_i
        c_i = powmod(m, add(s_i,d_i), self.N)
        s = get_random_int(self.N)
        c = get_random_int(self.N)
        r= add(s,multiply(c,add(s_i,d_i)))
        m_s = powmod(m, s, self.N)
        g_s = powmod(self.g, s, self.N)
        proof = [m, (g_s, m_s), c_i, r, c, self.id] #
        sigma = (c_i, proof)

        for computer in self.I:
            computer.receive_sigma(sigma)

        return sigma

    '''
    For every sigma in self.sigmas, where sigma is a signature and a proof,
    verify that the proof holds, and return True or False.
    '''
    def signature_share_verification(self):
        for sigma in self.sigmas:
            (c_i, proof) = sigma
            [m, (g_s, m_s), c_i, r, c, s_id] = proof
            b_ti0 = self.b_i_j[s_id][0]
            h_ti = self.presigning_data[self.I].received_h_t_i[s_id]
            if powmod(self.g, r, self.N) != mod(g_s*powmod(b_ti0*h_ti, c, self.N), self.N):
                return False
            if powmod(m, r, self.N) != mod(m_s*powmod(c_i, c, self.N), self.N):
                return False

        return True 

    ##############################################
    # Functions for the Share Combining (6.2.5)
    ##############################################

    '''
    Assuming we have already received the sigmas from the
    other k-1 computers, we will now combine the shares and
    return the appropriate signature for the desired message.
    '''
    def combine_signatures(self, m):
        # We assume that the signature shares have been computed,
        # broadcasted and verified already, and that they are
        # stored in self.sigmas
        product_c_t_i = mod(reduce(multiply, [sigma[0] for sigma in self.sigmas]), self.N)
        
        # Calculate the final signature = m^(-x_I * M) * the product
        self.signature = mod(multiply(product_c_t_i, powmod(m, -1 * multiply(self.presigning_data[self.I].x_I, self.M), self.N)), self.N)


    ##############################################
    # Functions for Private Key Generation
    ##############################################

    def receive_phi(self, from_id, phi_i_j):
        self.phi_i_j[from_id] = phi_i_j

    def receive_sum_phi_j(self, from_id, sum_phi_j):
        self.sum_phi_i_j[from_id] = sum_phi_j

    def receive_message_i(self, from_id, message):
        self.message_i[from_id] = message

    def create_phi_i(self,):
        self.phi_i =-add(self.p_i,self.q_i)
        if self.id == 0:
            self.phi_i = add(add(self.N,self.phi_i), 1)

    def distribute_phi_i_j(self,):
        phi_i_j = sum_genereator(self.phi_i, n, self.e)
        assert mod(reduce(add, phi_i_j), self.e) == mod(self.phi_i,self.e)
        
        for computer in self.network.nodes:
            computer.receive_phi(self.id, phi_i_j[computer.id])

    def distribute_sum_phi_j(self,):
        #Calculates sum of phi_i_j and distributes it to everyone
        sum_phi_j = reduce(add,self.phi_i_j)
        for computer in self.network.nodes:
            computer.receive_sum_phi_j(self.id, sum_phi_j)

    def generate_phi_and_psi(self,):
        self.sum_phi = reduce(add,self.sum_phi_i_j)
        self.psi = mod(self.sum_phi, self.e)
        self.psi_inv = powmod(self.psi, -1, self.e)

    def generate_d_i(self,):
        self.d_i = floor_divide(-multiply(self.phi_i,self.psi_inv), self.e)
        if self.id == 0:
            self.d_i = floor_divide(1-multiply(self.phi_i,self.psi_inv), self.e)

    def generate_message_i(self,message):
        self.network.nodes[0].receive_message_i(self.id, powmod(message,multiply(self.d_i,self.e),self.N))

    def process_messages(self,message):
        m_prime = mod(reduce(multiply,self.message_i), self.N)
        correct = n

        for i in range(n):
            if mod(message, self.N) == mod(multiply(m_prime, powmod(message, multiply(i,self.e), self.N)),self.N):
                correct = i
                break
        assert correct != n
        self.d_i +=correct


    def __str__(self):
        return "Computer "+str(self.id)

if __name__=="__main__":
    
    n=input('Enter how many parties are there, ex 8: ')
    k=input('Set the threshold of how many parties must agree to produce a signature, ex 3: ')
    agree = raw_input('Indicate which parties agree, ex: 0,2,4,5: ')
    agreelist = [int(i) for i in agree.split(',')]

    network = Network(agreelist)
    network.setup()
    while True:
        message = input('what is the message, ex 100? ')
        network.sign(message)
        agree = raw_input('Indicate which parties agree, ex: 0,2,4,5: ')
        if agree == "":
            agreelist = []
        else:
            agreelist = [int(i) for i in agree.split(',')]
        for computer in network.nodes:
            if computer.id in agreelist:
                computer.change_choice(True)
            else:
                computer.change_choice(False)
        

